using System.Windows.Input;

namespace Laitp.Desktop;

/// <summary>最简命令实现，支持同步/异步执行与 WPF 命令重查询。</summary>
public sealed class RelayCommand : ICommand
{
    private readonly Func<object?, Task>? _asyncExecute;
    private readonly Action<object?>? _execute;
    private readonly Predicate<object?>? _canExecute;

    public RelayCommand(Action<object?> execute, Predicate<object?>? canExecute = null)
    {
        _execute = execute;
        _canExecute = canExecute;
    }

    public RelayCommand(Func<object?, Task> execute, Predicate<object?>? canExecute = null)
    {
        _asyncExecute = execute;
        _canExecute = canExecute;
    }

    public bool CanExecute(object? parameter) => _canExecute?.Invoke(parameter) ?? true;

    public async void Execute(object? parameter)
    {
        if (_asyncExecute is not null)
        {
            await _asyncExecute(parameter);
            return;
        }

        _execute?.Invoke(parameter);
    }

    public event EventHandler? CanExecuteChanged
    {
        add => CommandManager.RequerySuggested += value;
        remove => CommandManager.RequerySuggested -= value;
    }
}
