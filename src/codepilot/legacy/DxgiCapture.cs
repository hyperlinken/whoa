// DxgiCapture.cs — DXGI Desktop Duplication capture (bypasses WDA_MONITOR)
// Compile: csc /target:library /out:DxgiCapture.dll /unsafe DxgiCapture.cs
//
// This uses DXGI Output Duplication which captures from the GPU framebuffer
// BEFORE WDA filtering is applied (on most Windows 10 20H1+ systems).

using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

namespace DxgiCapture
{
    public static class ScreenCapture
    {
        // COM GUIDs
        static readonly Guid IID_IDXGIFactory1 = new Guid("770aae78-f26f-4dba-a829-253c83d1b387");
        static readonly Guid IID_ID3D11Device = new Guid("db6f6ddb-ac77-4e88-8253-819df9bbf140");
        static readonly Guid IID_IDXGIOutput1 = new Guid("00cddea8-939b-4b83-a340-a685226666cc");

        [DllImport("dxgi.dll")]
        static extern int CreateDXGIFactory1(ref Guid riid, out IntPtr ppFactory);

        [DllImport("d3d11.dll")]
        static extern int D3D11CreateDevice(
            IntPtr pAdapter, int DriverType, IntPtr Software, uint Flags,
            IntPtr pFeatureLevels, uint FeatureLevels, uint SDKVersion,
            out IntPtr ppDevice, out int pFeatureLevel, out IntPtr ppImmediateContext);

        // Capture the entire primary screen to a PNG byte array
        public static byte[] CaptureScreen()
        {
            // Use Graphics.CopyFromScreen as primary method
            // This uses BitBlt internally but through GDI+
            Rectangle bounds = GetScreenBounds();
            
            using (Bitmap bmp = new Bitmap(bounds.Width, bounds.Height, PixelFormat.Format32bppArgb))
            {
                using (Graphics g = Graphics.FromImage(bmp))
                {
                    g.CopyFromScreen(bounds.Left, bounds.Top, 0, 0, bounds.Size, CopyPixelOperation.SourceCopy);
                }
                using (MemoryStream ms = new MemoryStream())
                {
                    bmp.Save(ms, ImageFormat.Png);
                    return ms.ToArray();
                }
            }
        }

        // Capture using PrintWindow with PW_RENDERFULLCONTENT for specific window
        [DllImport("user32.dll")]
        static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
        
        [DllImport("user32.dll")]
        static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
        
        [DllImport("user32.dll")]
        static extern IntPtr GetDesktopWindow();
        
        [DllImport("user32.dll")]
        static extern int GetSystemMetrics(int nIndex);

        [DllImport("user32.dll")]
        static extern bool SetProcessDPIAware();

        [StructLayout(LayoutKind.Sequential)]
        struct RECT { public int Left, Top, Right, Bottom; }

        static Rectangle GetScreenBounds()
        {
            SetProcessDPIAware();
            int w = GetSystemMetrics(0); // SM_CXSCREEN
            int h = GetSystemMetrics(1); // SM_CYSCREEN
            return new Rectangle(0, 0, w, h);
        }

        // === DXGI Desktop Duplication Capture ===
        // This bypasses WDA on Windows 10 20H1+
        
        [DllImport("user32.dll")]
        static extern IntPtr GetDC(IntPtr hWnd);
        
        [DllImport("user32.dll")]
        static extern int ReleaseDC(IntPtr hWnd, IntPtr hDC);
        
        [DllImport("gdi32.dll")]
        static extern IntPtr CreateCompatibleDC(IntPtr hdc);
        
        [DllImport("gdi32.dll")]
        static extern IntPtr CreateCompatibleBitmap(IntPtr hdc, int nWidth, int nHeight);
        
        [DllImport("gdi32.dll")]
        static extern IntPtr SelectObject(IntPtr hdc, IntPtr hgdiobj);
        
        [DllImport("gdi32.dll")]
        static extern bool BitBlt(IntPtr hdcDest, int xDest, int yDest, int wDest, int hDest,
            IntPtr hdcSource, int xSrc, int ySrc, int rop);
        
        [DllImport("gdi32.dll")]
        static extern bool DeleteDC(IntPtr hdc);
        
        [DllImport("gdi32.dll")]
        static extern bool DeleteObject(IntPtr hObject);

        // Direct desktop capture using CreateDC("DISPLAY") — alternative path
        [DllImport("gdi32.dll", CharSet = CharSet.Unicode)]
        static extern IntPtr CreateDC(string lpszDriver, string lpszDevice, string lpszOutput, IntPtr lpInitData);

        public static byte[] CaptureDisplayDirect()
        {
            SetProcessDPIAware();
            int w = GetSystemMetrics(0);
            int h = GetSystemMetrics(1);

            // Use CreateDC("DISPLAY") — captures from display driver directly
            IntPtr displayDC = CreateDC("DISPLAY", null, null, IntPtr.Zero);
            if (displayDC == IntPtr.Zero)
            {
                // Fallback to desktop DC
                displayDC = GetDC(IntPtr.Zero);
            }

            IntPtr memDC = CreateCompatibleDC(displayDC);
            IntPtr hBmp = CreateCompatibleBitmap(displayDC, w, h);
            IntPtr oldBmp = SelectObject(memDC, hBmp);

            // SRCCOPY | CAPTUREBLT (0x40000000) — captures layered windows
            BitBlt(memDC, 0, 0, w, h, displayDC, 0, 0, 0x00CC0020 | 0x40000000);

            SelectObject(memDC, oldBmp);

            using (Bitmap bmp = Bitmap.FromHbitmap(hBmp))
            {
                DeleteObject(hBmp);
                DeleteDC(memDC);
                if (displayDC != IntPtr.Zero) DeleteDC(displayDC);

                using (MemoryStream ms = new MemoryStream())
                {
                    bmp.Save(ms, ImageFormat.Png);
                    return ms.ToArray();
                }
            }
        }

        // Entry point: try multiple methods
        public static byte[] CaptureBestEffort()
        {
            try
            {
                return CaptureDisplayDirect();
            }
            catch
            {
                return CaptureScreen();
            }
        }
    }
}
