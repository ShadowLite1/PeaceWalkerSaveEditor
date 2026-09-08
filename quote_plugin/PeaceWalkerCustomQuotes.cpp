#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <MinHook.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <regex>
#include <sstream>
#include <string>
#include <unordered_map>

namespace fs = std::filesystem;

namespace {
constexpr uintptr_t kQuoteResolverRva = 0x356300;
constexpr uintptr_t kStringCopyRva = 0x10BEC0;
constexpr wchar_t kGameExe[] = L"METAL GEAR SOLID PEACE WALKER.exe";
constexpr wchar_t kSidecarSuffix[] = L".pwquotes.json";

using QuoteResolver = void* (__fastcall*)(void*, void*, uint32_t, void*);
using StringCopy = void* (__fastcall*)(void*, void*, const char*, uintptr_t);

QuoteResolver g_original_resolver = nullptr;
StringCopy g_original_copy = nullptr;
std::unordered_map<uint32_t, std::string> g_quotes;
std::mutex g_quotes_mutex;
std::atomic_bool g_running{true};
thread_local uint32_t g_active_quote = 0;
thread_local bool g_has_active_quote = false;
fs::path g_loaded_sidecar;
fs::file_time_type g_loaded_write_time{};

void Log(const std::string& message) {
    wchar_t module_path[MAX_PATH]{};
    GetModuleFileNameW(nullptr, module_path, MAX_PATH);
    fs::path log_path = fs::path(module_path).parent_path() / L"PeaceWalkerCustomQuotes.log";
    std::ofstream output(log_path, std::ios::app);
    if (output) output << message << '\n';
}

std::string DecodeJsonString(const std::string& value) {
    std::string result;
    result.reserve(value.size());
    for (size_t i = 0; i < value.size(); ++i) {
        if (value[i] != '\\' || i + 1 >= value.size()) {
            result.push_back(value[i]);
            continue;
        }
        const char escaped = value[++i];
        switch (escaped) {
        case '"': result.push_back('"'); break;
        case '\\': result.push_back('\\'); break;
        case '/': result.push_back('/'); break;
        case 'b': result.push_back('\b'); break;
        case 'f': result.push_back('\f'); break;
        case 'n': result.push_back('\n'); break;
        case 'r': result.push_back('\r'); break;
        case 't': result.push_back('\t'); break;
        default: result.push_back(escaped); break;
        }
    }
    return result;
}

bool ParseSidecar(const fs::path& path, std::unordered_map<uint32_t, std::string>& quotes) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return false;
    std::ostringstream buffer;
    buffer << input.rdbuf();
    const std::string json = buffer.str();
    const std::regex entry(
        R"quote("runtime_index"\s*:\s*(\d+)\s*,\s*"text"\s*:\s*"((?:\\.|[^"\\])*)")quote",
        std::regex::ECMAScript);
    for (std::sregex_iterator it(json.begin(), json.end(), entry), end; it != end; ++it) {
        const auto index = static_cast<uint32_t>(std::stoul((*it)[1].str()));
        quotes[index] = DecodeJsonString((*it)[2].str());
    }
    return !quotes.empty();
}

fs::path FindNewestSidecar() {
    wchar_t module_path[MAX_PATH]{};
    GetModuleFileNameW(nullptr, module_path, MAX_PATH);
    const fs::path game_dir = fs::path(module_path).parent_path();
    const fs::path root = game_dir.parent_path() / L"mgspw_savedata_win";
    if (!fs::exists(root)) return {};

    fs::path newest;
    fs::file_time_type newest_time{};
    std::error_code error;
    for (fs::recursive_directory_iterator it(root, fs::directory_options::skip_permission_denied, error), end;
         it != end; it.increment(error)) {
        if (error || !it->is_regular_file(error)) continue;
        const std::wstring filename = it->path().filename().wstring();
        if (!filename.ends_with(kSidecarSuffix)) continue;
        fs::path save_path = it->path().parent_path() /
            filename.substr(0, filename.size() - std::wstring(kSidecarSuffix).size());
        if (!fs::exists(save_path, error)) continue;
        const auto write_time = fs::last_write_time(save_path, error);
        if (!error && (newest.empty() || write_time > newest_time)) {
            newest = it->path();
            newest_time = write_time;
        }
    }
    return newest;
}

void RefreshQuotes() {
    const fs::path sidecar = FindNewestSidecar();
    if (sidecar.empty()) return;
    std::error_code error;
    const auto write_time = fs::last_write_time(sidecar, error);
    if (error || (sidecar == g_loaded_sidecar && write_time == g_loaded_write_time)) return;

    std::unordered_map<uint32_t, std::string> parsed;
    if (!ParseSidecar(sidecar, parsed)) {
        Log("Could not parse custom quote file: " + sidecar.string());
        return;
    }
    {
        std::lock_guard lock(g_quotes_mutex);
        g_quotes = std::move(parsed);
    }
    g_loaded_sidecar = sidecar;
    g_loaded_write_time = write_time;
    Log("Loaded custom quotes from: " + sidecar.string());
}

void* __fastcall HookQuoteResolver(void* first, void* second, uint32_t index, void* fourth) {
    const uint32_t previous_index = g_active_quote;
    const bool previous_active = g_has_active_quote;
    g_active_quote = index;
    g_has_active_quote = true;
    void* result = g_original_resolver(first, second, index, fourth);
    g_active_quote = previous_index;
    g_has_active_quote = previous_active;
    return result;
}

bool IsDetailsQuoteDestination(const void* destination) {
    __try {
        return destination != nullptr && *static_cast<const uint16_t*>(destination) == 0x00ff;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

void* __fastcall HookStringCopy(void* first, void* destination, const char* text, uintptr_t fourth) {
    if (g_has_active_quote && IsDetailsQuoteDestination(destination)) {
            thread_local std::string replacement;
            std::lock_guard lock(g_quotes_mutex);
            const auto found = g_quotes.find(g_active_quote);
            if (found != g_quotes.end()) {
                replacement = found->second;
                text = replacement.c_str();
            }
    }
    return g_original_copy(first, destination, text, fourth);
}

DWORD WINAPI PluginMain(void*) {
    HMODULE game = nullptr;
    while (g_running && (game = GetModuleHandleW(kGameExe)) == nullptr) Sleep(250);
    if (!game) return 0;

    RefreshQuotes();
    if (MH_Initialize() != MH_OK) {
        Log("MinHook initialization failed.");
        return 0;
    }
    const auto base = reinterpret_cast<uintptr_t>(game);
    if (MH_CreateHook(reinterpret_cast<void*>(base + kQuoteResolverRva), &HookQuoteResolver,
                      reinterpret_cast<void**>(&g_original_resolver)) != MH_OK ||
        MH_CreateHook(reinterpret_cast<void*>(base + kStringCopyRva), &HookStringCopy,
                      reinterpret_cast<void**>(&g_original_copy)) != MH_OK ||
        MH_EnableHook(MH_ALL_HOOKS) != MH_OK) {
        Log("Could not install custom quote hooks. The game version may be unsupported.");
        return 0;
    }
    Log("Custom quote support active.");
    while (g_running) {
        Sleep(2000);
        RefreshQuotes();
    }
    return 0;
}
}  // namespace

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        if (HANDLE thread = CreateThread(nullptr, 0, PluginMain, nullptr, 0, nullptr)) CloseHandle(thread);
    } else if (reason == DLL_PROCESS_DETACH) {
        g_running = false;
    }
    return TRUE;
}
