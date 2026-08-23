
using System;
using System.Reflection;
class P {
    static void Main() {
        var asm = Assembly.LoadFrom(@"C:\Users\ravij\Downloads\OA\CodePilot_GeminiWebAPI_V13\agent\DxgiCapture.dll");
        var t = asm.GetType("DxgiCapture.ScreenCapture");
        var m = t.GetMethod("CaptureBestEffort");
        byte[] data = (byte[])m.Invoke(null, null);
        Console.Write(Convert.ToBase64String(data));
    }
}
