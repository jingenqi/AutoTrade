"""
MT5-ZMQ EA高级测试与验证脚本
--------------------------------
本脚本扮演Python核心控制器的角色，用于对MQL5 EA进行全面的功能和协议验证。
它执行以下操作:
1.  **同步握手**: 启动时与EA进行REQ/REP握手，确保连接建立。
2.  **事件监听**: 订阅并接收EA通过PUB/SUB通道广播的交易事件和心跳。
3.  **数据契约验证**: 使用Pydantic模型严格验证每个交易事件的JSON结构和数据类型，
    确保其符合 `doc.md` 中定义的规范。
4.  **实时反馈**: 对收到的每条消息进行解析和验证，并以彩色高亮的形式实时打印
    PASS/FAIL结果。
5.  **统计报告**: 在脚本终止时，打印本次测试的总结，包括处理的消息总数、
    成功和失败的计数。
"""
import zmq
import json
import time
from datetime import datetime

# Pydantic和Rich用于验证和美化输出
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live

# 从核心模块导入共享的数据契约
from python.core.events import create_event_from_dict, HeartbeatEvent
# 从新的配置文件中导入所有ZMQ设置
from python.config.settings import (
    ZMQ_SYNC_URI, ZMQ_BUS_URI, MSG_SYNC_REQUEST, MSG_SYNC_RESPONSE
)

# 心跳常量（如果settings.py中没有定义）
MSG_HEARTBEAT = "HEARTBEAT"

# ZMQ配置 (已移至 mt5_copier/python/config/settings.py)

# --- 测试统计 ---
class HarnessStats:
    def __init__(self):
        self.events_received = 0
        self.events_passed = 0
        self.events_failed = 0
        self.heartbeats = 0
        self.start_time = time.time()

    def generate_summary_panel(self) -> Panel:
        uptime = time.time() - self.start_time
        summary_table = Table(show_header=False, box=None, padding=(0, 1))
        summary_table.add_column(style="bold magenta")
        summary_table.add_column(style="bold cyan")
        summary_table.add_row("Total Events Processed:", str(self.events_received))
        summary_table.add_row("  - Passed Validation:", f"[green]{self.events_passed}[/green]")
        summary_table.add_row("  - Failed Validation:", f"[red]{self.events_failed}[/red]")
        summary_table.add_row("Heartbeats Received:", str(self.heartbeats))
        summary_table.add_row("Test Duration:", f"{uptime:.2f} seconds")
        
        return Panel(
            summary_table,
            title="[bold blue]Test Summary[/bold blue]",
            border_style="blue",
            padding=(1, 2)
        )

# --- 主测试逻辑 ---
def run_ea_test():
    console = Console()
    stats = HarnessStats()

    console.rule("[bold yellow]MT5 EA Advanced Test Harness[/bold yellow]")
    console.print(f"Test started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", style="dim")

    context = zmq.Context()
    rep_socket = context.socket(zmq.REP)
    sub_socket = context.socket(zmq.SUB)

    try:
        # 1. 同步握手
        console.print("\n[bold]Step 1: Performing Handshake[/bold]")
        rep_socket.bind(ZMQ_SYNC_URI)
        console.print(f"   [cyan]REP socket bound to:[/] {ZMQ_SYNC_URI}")
        console.print("   [yellow]Waiting for EA to send handshake request... (Please start EA now)[/yellow]")

        if rep_socket.poll(30000): # 30秒超时
            message = rep_socket.recv_string()
            console.print(f"   [green]Received:[/] '{message}'")
            if message == MSG_SYNC_REQUEST:
                rep_socket.send_string(MSG_SYNC_RESPONSE)
                console.print(f"   [green]Sent    :[/] '{MSG_SYNC_RESPONSE}'")
                console.print("   [bold green]✓ Handshake successful![/bold green]")
            else:
                console.print(f"   [bold red]✗ ERROR: Invalid handshake message![/bold red]")
                return
        else:
            console.print("   [bold red]✗ ERROR: Timeout waiting for EA handshake.[/bold red]")
            return

        # 2. 监听事件
        console.print("\n[bold]Step 2: Listening for Trade Events & Heartbeats[/bold]")
        sub_socket.connect(ZMQ_BUS_URI)
        sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")
        console.print(f"   [cyan]SUB socket connected to:[/] {ZMQ_BUS_URI}")
        console.print("[dim](Press Ctrl+C to stop the test and see the summary)[/dim]\n")

        while True:
            if sub_socket.poll(1000): # 1秒轮询超时
                raw_message = sub_socket.recv_string()
                stats.events_received += 1
                
                panel_title = f"[bold]Event #{stats.events_received} @ {datetime.now().strftime('%H:%M:%S')}[/bold]"
                
                try:
                    data = json.loads(raw_message)
                    
                    # 检查是否为心跳
                    if data.get("event_type") == MSG_HEARTBEAT:
                        stats.heartbeats += 1
                        # Validate heartbeat against its own model
                        hb_event = HeartbeatEvent(**data)
                        stats.events_passed += 1
                        
                        hb_table = Table(show_header=False, box=None)
                        hb_table.add_column(style="magenta")
                        hb_table.add_column()
                        hb_table.add_row("event_type:", hb_event.event_type)
                        hb_table.add_row("timestamp:", str(hb_event.timestamp))
                        
                        console.print(Panel(
                            hb_table,
                            title=f"{panel_title} [cyan]HEARTBEAT PASS[/cyan]",
                            border_style="cyan"
                        ))
                        continue # Go to next message
                        
                    # 验证交易事件
                    event = create_event_from_dict(data)
                    stats.events_passed += 1
                    
                    # 成功: 打印绿色面板和事件详情
                    table = Table(show_header=False, box=None)
                    table.add_column(style="magenta")
                    table.add_column()
                    for key, value in data.items():
                        table.add_row(f"{key}:", str(value))
                        
                    console.print(Panel(
                        table,
                        title=f"{panel_title} [green]PASS[/green]",
                        border_style="green"
                    ))

                except json.JSONDecodeError:
                    stats.events_failed += 1
                    console.print(Panel(
                        f"[bold]Raw Message:[/bold]\n{raw_message}",
                        title=f"{panel_title} [red]FAIL: Invalid JSON[/red]",
                        border_style="red"
                    ))
                except ValidationError as e:
                    stats.events_failed += 1
                    console.print(Panel(
                        f"[bold]Invalid Data Structure. Errors:[/bold]\n[yellow]{e}[/yellow]\n\n[bold]Raw Message:[/bold]\n{raw_message}",
                        title=f"{panel_title} [red]FAIL: Event Creation/Validation[/red]",
                        border_style="red"
                    ))
            
    except KeyboardInterrupt:
        console.print("\n\n[yellow]Test interrupted by user.[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]An unexpected error occurred: {e}[/bold red]")
    finally:
        # 清理资源并打印总结
        console.print("\nCleaning up resources...")
        rep_socket.close()
        sub_socket.close()
        context.term()
        
        console.print(stats.generate_summary_panel())
        console.rule("[bold yellow]Test Finished[/bold yellow]")


if __name__ == "__main__":
    run_ea_test() 