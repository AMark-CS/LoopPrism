"""CLI entry point for loopprism."""

from typing import Optional

import typer
import uvicorn

from .. import __version__
from ..utils.config import config
from ..utils.logging import setup_logging
from ..trace.collector import TraceCollector
from ..proxy.server import ProxyServer
from ..api.app import create_app

app = typer.Typer(
    name="loopprism",
    help="See what your agents actually do.",
    invoke_without_command=True,
)


@app.callback()
def _version_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
    ),
) -> None:
    if version:
        typer.echo(f"loopprism {__version__}")
        raise typer.Exit()


@app.command()
def proxy(
    port: int = typer.Option(
        4317,
        "--port",
        "-p",
        help="Proxy listen port.",
    ),
    dashboard_port: int = typer.Option(
        8080,
        "--dashboard-port",
        "-d",
        help="Dashboard port.",
    ),
    db_path: str = typer.Option(
        config.db_path,
        "--db",
        help="SQLite database path.",
    ),
    no_dashboard: bool = typer.Option(
        False,
        "--no-dashboard",
        help="Disable the built-in dashboard.",
    ),
    export_endpoint: Optional[str] = typer.Option(
        None,
        "--export-endpoint",
        help="OTLP endpoint for exporting traces.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Enable debug logging.",
    ),
) -> None:
    """Start the MCP interception proxy with built-in dashboard.

    Point your MCP clients at http://localhost:PORT/<server-name>
    and open the dashboard to see every tool call.
    """
    import asyncio
    import os
    from pathlib import Path

    # Expand ~ in db_path
    db_path_expanded = str(Path(db_path).expanduser())
    os.makedirs(os.path.dirname(db_path_expanded), exist_ok=True)

    # Override config from CLI args
    config.proxy_port = port
    config.dashboard_port = dashboard_port
    config.db_path = db_path_expanded
    config.dashboard_enabled = not no_dashboard
    config.otlp_endpoint = export_endpoint
    config.verbose = verbose

    setup_logging(verbose=verbose)

    # Banner
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", style="bold cyan")
    table.add_column(style="white")
    table.add_row("Proxy:", f"http://localhost:{port}")
    table.add_row("Dashboard:", f"http://localhost:{dashboard_port}")
    table.add_row("Database:", db_path_expanded)

    panel = Panel(
        table,
        title="[bold]LoopPrism[/] — See what your agents actually do",
        border_style="cyan",
    )
    console.print()
    console.print(panel)
    console.print()
    console.print(
        "  Point your MCP clients to "
        f"[bold cyan]http://localhost:{port}/<server>[/]",
    )
    console.print()

    async def run() -> None:
        collector = TraceCollector(db_path=db_path_expanded)
        await collector.initialize()

        proxy_server = ProxyServer(
            host="127.0.0.1",
            port=port,
            collector=collector,
        )

        fastapi_app = create_app(
            collector=collector,
            dashboard_enabled=not no_dashboard,
        )

        # Run proxy and dashboard together
        uvicorn_config = uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=dashboard_port,
            log_level="info" if verbose else "warning",
        )
        api_server = uvicorn.Server(uvicorn_config)

        async with proxy_server:
            await asyncio.gather(
                proxy_server.serve(),
                api_server.serve(),
            )

    asyncio.run(run())


@app.command()
def analyze(
    trace_id: str = typer.Argument(..., help="Trace ID to analyze."),
    db_path: str = typer.Option(
        config.db_path,
        "--db",
        help="SQLite database path.",
    ),
) -> None:
    """Analyze a specific trace offline."""
    from pathlib import Path
    import asyncio

    db_path_expanded = str(Path(db_path).expanduser())

    async def _analyze() -> None:
        from ..trace.collector import TraceCollector
        from rich.console import Console
        from rich.table import Table

        console = Console()
        collector = TraceCollector(db_path=db_path_expanded)
        await collector.initialize()

        trace_data = await collector.get_trace(trace_id)
        if not trace_data:
            console.print(
                f"[red]Trace {trace_id} not found.[/]",
            )
            return

        trace, spans = trace_data

        table = Table(title=f"Trace: {trace_id}")
        table.add_column("Span", style="cyan")
        table.add_column("Latency", justify="right")
        table.add_column("MCP Server")
        table.add_column("Details")

        for span in spans:
            table.add_row(
                span.get("span_type", ""),
                f"{span.get('latency_ms', 0):.1f}ms",
                span.get("mcp_server_name", "-"),
                span.get("tool_name", "") or "",
            )

        console.print(table)

    asyncio.run(_analyze())


@app.command()
def dashboard(
    port: int = typer.Option(
        8080,
        "--port",
        "-p",
        help="Dashboard port.",
    ),
    db_path: str = typer.Option(
        config.db_path,
        "--db",
        help="SQLite database path.",
    ),
) -> None:
    """Start standalone dashboard (for remote trace storage)."""
    import asyncio
    from pathlib import Path

    db_path_expanded = str(Path(db_path).expanduser())

    async def _serve() -> None:
        from ..trace.collector import TraceCollector
        from ..api.app import create_app

        collector = TraceCollector(db_path=db_path_expanded)
        await collector.initialize()

        fastapi_app = create_app(collector=collector, dashboard_enabled=True)

        uvicorn_config = uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=port,
            log_level="info",
        )
        await uvicorn.Server(uvicorn_config).serve()

    asyncio.run(_serve())


if __name__ == "__main__":
    app()
