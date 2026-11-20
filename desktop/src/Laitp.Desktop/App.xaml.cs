using System;
using System.Windows;
using Laitp.Core;

namespace Laitp.Desktop;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        if (e.Args.Length > 0 && e.Args[0] == "--self-test")
        {
            var output = e.Args.Length > 1 ? e.Args[1] : "self-test.json";
            var exitCode = SelfTest.Run(output);
            Shutdown(exitCode);
            return;
        }

        base.OnStartup(e);
    }
}
