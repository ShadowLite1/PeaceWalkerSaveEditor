#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <xaudio2.h>
#include <audioclient.h>
#include <mmdeviceapi.h>

#include <MinHook.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#pragma comment(lib, "ole32.lib")

namespace fs = std::filesystem;

namespace {
using XAudio2CreateFn = HRESULT(WINAPI*)(IXAudio2**, UINT32, XAUDIO2_PROCESSOR);
using CreateSourceVoiceFn = HRESULT(STDMETHODCALLTYPE*)(
    IXAudio2*, IXAudio2SourceVoice**, const WAVEFORMATEX*, UINT32, float,
    IXAudio2VoiceCallback*, const XAUDIO2_VOICE_SENDS*, const XAUDIO2_EFFECT_CHAIN*);
using SubmitSourceBufferFn = HRESULT(STDMETHODCALLTYPE*)(
    IXAudio2SourceVoice*, const XAUDIO2_BUFFER*, const XAUDIO2_BUFFER_WMA*);

struct AudioFormat {
    WORD tag{};
    WORD channels{};
    DWORD samples_per_sec{};
    DWORD avg_bytes_per_sec{};
    WORD block_align{};
    WORD bits_per_sample{};
    std::vector<std::uint8_t> extra;
};

struct CaptureJob {
    std::uint64_t sequence{};
    std::uintptr_t voice{};
    AudioFormat format;
    std::vector<std::uint8_t> audio;
    UINT32 play_begin{};
    UINT32 play_length{};
    UINT32 loop_count{};
};

XAudio2CreateFn g_original_xaudio2_create = nullptr;
CreateSourceVoiceFn g_original_create_source_voice = nullptr;
SubmitSourceBufferFn g_original_submit_source_buffer = nullptr;
std::unordered_map<IXAudio2SourceVoice*, AudioFormat> g_formats;
std::mutex g_formats_mutex;
std::unordered_set<IXAudio2SourceVoice*> g_unknown_voices_logged;
std::deque<CaptureJob> g_jobs;
std::mutex g_jobs_mutex;
std::condition_variable g_jobs_ready;
std::atomic_bool g_running{true};
std::atomic_uint64_t g_sequence{0};
fs::path g_game_dir;
fs::path g_capture_dir;

fs::path ArmMarker() { return g_game_dir / L"scripts" / L"PWVoiceCapture.arm"; }

void Log(const std::string& message) {
    std::ofstream output(g_game_dir / L"PeaceWalkerVoiceCapture.log", std::ios::app);
    if (output) output << message << '\n';
}

AudioFormat CopyFormat(const WAVEFORMATEX* source) {
    AudioFormat result{};
    if (!source) return result;
    result.tag = source->wFormatTag;
    result.channels = source->nChannels;
    result.samples_per_sec = source->nSamplesPerSec;
    result.avg_bytes_per_sec = source->nAvgBytesPerSec;
    result.block_align = source->nBlockAlign;
    result.bits_per_sample = source->wBitsPerSample;
    if (source->cbSize) {
        const auto* bytes = reinterpret_cast<const std::uint8_t*>(source + 1);
        result.extra.assign(bytes, bytes + source->cbSize);
    }
    return result;
}

template <typename T>
void WriteValue(std::ofstream& output, T value) {
    output.write(reinterpret_cast<const char*>(&value), sizeof(value));
}

bool WriteWave(const fs::path& path, const CaptureJob& job) {
    std::ofstream output(path, std::ios::binary);
    if (!output) return false;
    const DWORD fmt_size = job.format.tag == WAVE_FORMAT_PCM && job.format.extra.empty()
        ? 16u : static_cast<DWORD>(18u + job.format.extra.size());
    const DWORD data_size = static_cast<DWORD>(job.audio.size());
    const DWORD riff_size = 4u + 8u + fmt_size + 8u + data_size;
    output.write("RIFF", 4); WriteValue(output, riff_size); output.write("WAVE", 4);
    output.write("fmt ", 4); WriteValue(output, fmt_size);
    WriteValue(output, job.format.tag);
    WriteValue(output, job.format.channels);
    WriteValue(output, job.format.samples_per_sec);
    WriteValue(output, job.format.avg_bytes_per_sec);
    WriteValue(output, job.format.block_align);
    WriteValue(output, job.format.bits_per_sample);
    if (fmt_size > 16) {
        const WORD extra_size = static_cast<WORD>(job.format.extra.size());
        WriteValue(output, extra_size);
        if (!job.format.extra.empty()) {
            output.write(reinterpret_cast<const char*>(job.format.extra.data()), job.format.extra.size());
        }
    }
    output.write("data", 4); WriteValue(output, data_size);
    output.write(reinterpret_cast<const char*>(job.audio.data()), job.audio.size());
    return static_cast<bool>(output);
}

void LoopbackCaptureWorker() {
    if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) {
        Log("WASAPI: COM initialization failed");
        return;
    }
    IMMDeviceEnumerator* enumerator = nullptr;
    IMMDevice* device = nullptr;
    IAudioClient* client = nullptr;
    IAudioCaptureClient* capture = nullptr;
    WAVEFORMATEX* mix = nullptr;
    HRESULT hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                                  __uuidof(IMMDeviceEnumerator),
                                  reinterpret_cast<void**>(&enumerator));
    if (SUCCEEDED(hr)) hr = enumerator->GetDefaultAudioEndpoint(eRender, eConsole, &device);
    if (SUCCEEDED(hr)) hr = device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr,
                                             reinterpret_cast<void**>(&client));
    if (SUCCEEDED(hr)) hr = client->GetMixFormat(&mix);
    if (SUCCEEDED(hr)) hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED,
        AUDCLNT_STREAMFLAGS_LOOPBACK, 0, 0, mix, nullptr);
    if (SUCCEEDED(hr)) hr = client->GetService(__uuidof(IAudioCaptureClient),
                                               reinterpret_cast<void**>(&capture));
    if (SUCCEEDED(hr)) hr = client->Start();
    if (FAILED(hr)) {
        Log("WASAPI: unable to initialize loopback capture");
        if (mix) CoTaskMemFree(mix);
        if (capture) capture->Release();
        if (client) client->Release();
        if (device) device->Release();
        if (enumerator) enumerator->Release();
        CoUninitialize();
        return;
    }

    Log("WASAPI loopback ready");
    bool was_armed = false;
    std::vector<std::uint8_t> recording;
    while (g_running) {
        const bool armed = fs::exists(ArmMarker());
        if (armed && !was_armed) {
            recording.clear();
            Log("WASAPI capture armed");
        }

        UINT32 packet_frames = 0;
        while (SUCCEEDED(capture->GetNextPacketSize(&packet_frames)) && packet_frames) {
            BYTE* data = nullptr;
            UINT32 frames = 0;
            DWORD flags = 0;
            if (FAILED(capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr))) break;
            if (armed) {
                const std::size_t byte_count =
                    static_cast<std::size_t>(frames) * mix->nBlockAlign;
                const std::size_t old_size = recording.size();
                recording.resize(old_size + byte_count);
                if ((flags & AUDCLNT_BUFFERFLAGS_SILENT) || !data)
                    std::fill(recording.begin() + old_size, recording.end(), 0);
                else
                    std::copy(data, data + byte_count, recording.begin() + old_size);
            }
            capture->ReleaseBuffer(frames);
        }

        if (!armed && was_armed && !recording.empty()) {
            CaptureJob job{};
            job.format = CopyFormat(mix);
            job.audio = std::move(recording);
            const auto stamp = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();
            const fs::path directory = g_game_dir / L"voice_captures";
            std::error_code error;
            fs::create_directories(directory, error);
            const fs::path output = directory /
                (L"loopback_" + std::to_wstring(stamp) + L".wav");
            if (WriteWave(output, job))
                Log("WASAPI capture saved: " + output.string());
            else
                Log("WASAPI: failed to save capture");
            recording.clear();
        }
        was_armed = armed;
        Sleep(5);
    }
    client->Stop();
    if (mix) CoTaskMemFree(mix);
    capture->Release(); client->Release(); device->Release(); enumerator->Release();
    CoUninitialize();
}

void CaptureWorker() {
    std::ofstream manifest;
    while (g_running || !g_jobs.empty()) {
        CaptureJob job;
        {
            std::unique_lock lock(g_jobs_mutex);
            g_jobs_ready.wait_for(lock, std::chrono::milliseconds(250), [] {
                return !g_running || !g_jobs.empty();
            });
            if (g_jobs.empty()) continue;
            job = std::move(g_jobs.front());
            g_jobs.pop_front();
        }
        if (g_capture_dir.empty()) {
            const auto now = std::chrono::system_clock::now();
            const auto stamp = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
            g_capture_dir = g_game_dir / L"voice_captures" / std::to_wstring(stamp);
            std::error_code error;
            fs::create_directories(g_capture_dir, error);
            manifest.open(g_capture_dir / L"manifest.csv", std::ios::app);
            if (manifest) manifest << "file,voice_pointer,format,channels,sample_rate,bits,bytes,duration_seconds,play_begin,play_length,loop_count\n";
        }
        std::ostringstream name;
        name << "buffer_" << std::setfill('0') << std::setw(6) << job.sequence << ".wav";
        const fs::path wave_path = g_capture_dir / name.str();
        if (!WriteWave(wave_path, job)) continue;
        const double duration = job.format.avg_bytes_per_sec
            ? static_cast<double>(job.audio.size()) / job.format.avg_bytes_per_sec : 0.0;
        if (manifest) {
            manifest << name.str() << ",0x" << std::hex << job.voice << std::dec << ','
                     << job.format.tag << ',' << job.format.channels << ','
                     << job.format.samples_per_sec << ',' << job.format.bits_per_sample << ','
                     << job.audio.size() << ',' << std::fixed << std::setprecision(4) << duration << ','
                     << job.play_begin << ',' << job.play_length << ',' << job.loop_count << '\n';
            manifest.flush();
        }
    }
}

HRESULT STDMETHODCALLTYPE HookSubmitSourceBuffer(
    IXAudio2SourceVoice* self, const XAUDIO2_BUFFER* buffer, const XAUDIO2_BUFFER_WMA* wma) {
    // WASAPI loopback below captures the audible result. Keep this hook only
    // for discovering XAudio2 voices; do not dump every mixer fragment.
    if (false && buffer && buffer->pAudioData && buffer->AudioBytes && fs::exists(ArmMarker())) {
        AudioFormat format{};
        bool inferred_format = false;
        {
            std::scoped_lock lock(g_formats_mutex);
            const auto found = g_formats.find(self);
            if (found != g_formats.end()) format = found->second;
        }
        // Some source voices exist before PatriotFix loads ASI plugins. XAudio2
        // does not expose their complete WAVEFORMATEX afterward, but it does
        // expose the input channel count and sample rate. Preserve those
        // buffers as assumed PCM16 so gameplay-only voices are no longer lost.
        if (!format.channels || !format.samples_per_sec) {
            XAUDIO2_VOICE_DETAILS details{};
            self->GetVoiceDetails(&details);
            if (details.InputChannels && details.InputSampleRate) {
                format.tag = WAVE_FORMAT_PCM;
                format.channels = static_cast<WORD>(details.InputChannels);
                format.samples_per_sec = details.InputSampleRate;
                format.bits_per_sample = 16;
                format.block_align = static_cast<WORD>(details.InputChannels * 2u);
                format.avg_bytes_per_sec = details.InputSampleRate * format.block_align;
                inferred_format = true;
            }
        }
        if (inferred_format) {
            std::scoped_lock lock(g_formats_mutex);
            if (g_unknown_voices_logged.insert(self).second) {
                std::ostringstream message;
                message << "Inferred pre-existing voice 0x" << std::hex
                        << reinterpret_cast<std::uintptr_t>(self) << std::dec
                        << " as PCM16: channels=" << format.channels
                        << " rate=" << format.samples_per_sec;
                Log(message.str());
            }
        }
        if (format.channels && format.samples_per_sec && buffer->AudioBytes <= 64u * 1024u * 1024u) {
            CaptureJob job{};
            job.sequence = ++g_sequence;
            job.voice = reinterpret_cast<std::uintptr_t>(self);
            job.format = std::move(format);
            job.audio.assign(buffer->pAudioData, buffer->pAudioData + buffer->AudioBytes);
            job.play_begin = buffer->PlayBegin;
            job.play_length = buffer->PlayLength;
            job.loop_count = buffer->LoopCount;
            {
                std::scoped_lock lock(g_jobs_mutex);
                if (g_jobs.size() < 2048) g_jobs.push_back(std::move(job));
            }
            g_jobs_ready.notify_one();
        }
    }
    return g_original_submit_source_buffer(self, buffer, wma);
}

HRESULT STDMETHODCALLTYPE HookCreateSourceVoice(
    IXAudio2* self, IXAudio2SourceVoice** source_voice, const WAVEFORMATEX* format,
    UINT32 flags, float max_ratio, IXAudio2VoiceCallback* callback,
    const XAUDIO2_VOICE_SENDS* sends, const XAUDIO2_EFFECT_CHAIN* effects) {
    const HRESULT result = g_original_create_source_voice(
        self, source_voice, format, flags, max_ratio, callback, sends, effects);
    if (SUCCEEDED(result) && source_voice && *source_voice) {
        {
            std::scoped_lock lock(g_formats_mutex);
            g_formats[*source_voice] = CopyFormat(format);
        }
        // IXAudio2SourceVoice::SubmitSourceBuffer is slot 21. Slot 24 is
        // ExitLoop; hooking that slot silently missed every submitted buffer.
        void* submit = (*reinterpret_cast<void***>(*source_voice))[21];
        if (!g_original_submit_source_buffer) {
            if (MH_CreateHook(submit, &HookSubmitSourceBuffer,
                              reinterpret_cast<void**>(&g_original_submit_source_buffer)) == MH_OK) {
                MH_EnableHook(submit);
                Log("SubmitSourceBuffer hook installed");
            }
        }
    }
    return result;
}

HRESULT WINAPI HookXAudio2Create(IXAudio2** audio, UINT32 flags, XAUDIO2_PROCESSOR processor) {
    const HRESULT result = g_original_xaudio2_create(audio, flags, processor);
    if (SUCCEEDED(result) && audio && *audio && !g_original_create_source_voice) {
        void* create_source = (*reinterpret_cast<void***>(*audio))[5];
        if (MH_CreateHook(create_source, &HookCreateSourceVoice,
                          reinterpret_cast<void**>(&g_original_create_source_voice)) == MH_OK) {
            MH_EnableHook(create_source);
            Log("CreateSourceVoice hook installed");
        }
    }
    return result;
}

bool InstallSharedVoiceHooks(HMODULE xaudio) {
    const auto create = reinterpret_cast<XAudio2CreateFn>(
        GetProcAddress(xaudio, "XAudio2Create"));
    if (!create) return false;

    IXAudio2* probe_engine = nullptr;
    if (FAILED(create(&probe_engine, 0, XAUDIO2_DEFAULT_PROCESSOR)) || !probe_engine) {
        Log("Unable to create probe XAudio2 engine");
        return false;
    }

    void* create_source = (*reinterpret_cast<void***>(probe_engine))[5];
    WAVEFORMATEX probe_format{};
    probe_format.wFormatTag = WAVE_FORMAT_PCM;
    probe_format.nChannels = 1;
    probe_format.nSamplesPerSec = 48000;
    probe_format.wBitsPerSample = 16;
    probe_format.nBlockAlign = 2;
    probe_format.nAvgBytesPerSec = 96000;

    IXAudio2SourceVoice* probe_voice = nullptr;
    const HRESULT voice_result = probe_engine->CreateSourceVoice(
        &probe_voice, &probe_format, 0, XAUDIO2_DEFAULT_FREQ_RATIO,
        nullptr, nullptr, nullptr);
    void* submit = probe_voice
        ? (*reinterpret_cast<void***>(probe_voice))[21]
        : nullptr;

    bool create_ok = false;
    bool submit_ok = false;
    if (create_source && !g_original_create_source_voice) {
        create_ok = MH_CreateHook(
            create_source, &HookCreateSourceVoice,
            reinterpret_cast<void**>(&g_original_create_source_voice)) == MH_OK;
    }
    if (submit && !g_original_submit_source_buffer) {
        submit_ok = MH_CreateHook(
            submit, &HookSubmitSourceBuffer,
            reinterpret_cast<void**>(&g_original_submit_source_buffer)) == MH_OK;
    }

    if (probe_voice) probe_voice->DestroyVoice();
    probe_engine->Release();

    if (create_ok && MH_EnableHook(create_source) == MH_OK)
        Log("Shared CreateSourceVoice hook installed");
    else if (!g_original_create_source_voice)
        Log("Unable to install shared CreateSourceVoice hook");

    if (submit_ok && MH_EnableHook(submit) == MH_OK)
        Log("Shared SubmitSourceBuffer hook installed");
    else if (!g_original_submit_source_buffer)
        Log("Unable to install shared SubmitSourceBuffer hook");

    return g_original_create_source_voice && g_original_submit_source_buffer;
}

DWORD WINAPI Initialize(void*) {
    wchar_t executable[MAX_PATH]{};
    GetModuleFileNameW(nullptr, executable, MAX_PATH);
    g_game_dir = fs::path(executable).parent_path();
    std::thread(CaptureWorker).detach();
    std::thread(LoopbackCaptureWorker).detach();
    HMODULE xaudio = GetModuleHandleW(L"xaudio2_9.dll");
    if (!xaudio) xaudio = LoadLibraryW(L"xaudio2_9.dll");
    if (!xaudio || MH_Initialize() != MH_OK) {
        Log("Unable to initialize XAudio2 capture hooks");
        return 1;
    }
    const bool shared_hooks = InstallSharedVoiceHooks(xaudio);

    // Keep the factory hook as a fallback for engines created later. The
    // shared method hooks above are what make late-loaded ASIs work reliably.
    void* create = reinterpret_cast<void*>(GetProcAddress(xaudio, "XAudio2Create"));
    if (create && MH_CreateHook(create, &HookXAudio2Create,
                               reinterpret_cast<void**>(&g_original_xaudio2_create)) == MH_OK) {
        MH_EnableHook(create);
    } else if (!shared_hooks) {
        Log("Unable to hook XAudio2Create");
        return 1;
    }
    Log(shared_hooks
        ? "Voice capture ready (shared hooks active)"
        : "Voice capture ready (factory hook fallback)");
    return 0;
}
} // namespace

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(instance);
        const HANDLE thread = CreateThread(nullptr, 0, Initialize, nullptr, 0, nullptr);
        if (thread) CloseHandle(thread);
    } else if (reason == DLL_PROCESS_DETACH) {
        g_running = false;
        g_jobs_ready.notify_all();
    }
    return TRUE;
}
