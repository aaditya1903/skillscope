"""SkillScope command-line interface."""

import typer
import uvicorn
from rich.console import Console

from skillscope import __version__

app = typer.Typer(no_args_is_help=True, help="Operate the SkillScope observatory.")
console = Console()


@app.command()
def version() -> None:
    """Print the installed SkillScope version."""
    console.print(__version__)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Interface on which to listen."),
    port: int = typer.Option(8000, min=1, max=65535, help="TCP port."),
    reload: bool = typer.Option(False, help="Reload when source files change."),
) -> None:
    """Start the development API server."""
    uvicorn.run("skillscope.api.main:app", host=host, port=port, reload=reload)


def main() -> None:
    """Run the command-line application."""
    app()


if __name__ == "__main__":
    main()
