import click

from slip import __version__


@click.group()
@click.version_option(version=__version__, prog_name="slip")
def slip():
    """Slip - Streamlined Integration Platform HDL compiler."""
    pass


def _fail(e: Exception, verbose: bool) -> None:
    """Report a compilation failure and exit non-zero."""
    import traceback

    from slip.errors.base import SlipError

    if verbose:
        traceback.print_exc()
    elif isinstance(e, SlipError):
        click.echo(str(e), err=True)
    else:
        click.echo(f"{type(e).__name__}: {e}", err=True)
        click.echo("(run with --verbose for a traceback)", err=True)
    raise SystemExit(1)


@slip.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--out-dir", default="./build", type=click.Path(file_okay=False), help="Output directory")
@click.option("-ip", "--ip-dirs", multiple=True, type=click.Path(exists=True, file_okay=False), help="IP source directories")
@click.option("-f", "--filelist", multiple=True, type=click.Path(exists=True, dir_okay=False), help="VCS-format filelist files")
@click.option("--verbose", is_flag=True, help="Print full tracebacks on error")
def build(file: str, out_dir: str, ip_dirs: tuple[str, ...], filelist: tuple[str, ...], verbose: bool):
    """Compile a .slip file to SystemVerilog."""
    from pathlib import Path
    from slip.cli._pipeline import run_build

    try:
        run_build(
            Path(file), Path(out_dir),
            [Path(d) for d in ip_dirs],
            [Path(f) for f in filelist],
        )
    except Exception as e:
        _fail(e, verbose)


@slip.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("-ip", "--ip-dirs", multiple=True, type=click.Path(exists=True, file_okay=False), help="IP source directories")
@click.option("-f", "--filelist", multiple=True, type=click.Path(exists=True, dir_okay=False), help="VCS-format filelist files")
@click.option("--verbose", is_flag=True, help="Print full tracebacks on error")
def check(file: str, ip_dirs: tuple[str, ...], filelist: tuple[str, ...], verbose: bool):
    """Check a .slip file for errors without generating output."""
    from pathlib import Path
    from slip.cli._pipeline import run_check

    try:
        run_check(Path(file), [Path(d) for d in ip_dirs], [Path(f) for f in filelist])
        click.echo("No errors found.")
    except Exception as e:
        _fail(e, verbose)


def main():
    slip()
