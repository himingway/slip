import click


@click.group()
def slip():
    """Slip - Streamlined Integration Platform HDL compiler."""
    pass


@slip.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("-o", "--out-dir", default="./build", type=click.Path(), help="Output directory")
@click.option("-ip", "--ip-dirs", multiple=True, type=click.Path(exists=True), help="IP source directories")
def build(file: str, out_dir: str, ip_dirs: tuple[str, ...]):
    """Compile a .slip file to SystemVerilog."""
    from pathlib import Path
    from slip.cli._pipeline import run_build

    try:
        run_build(Path(file), Path(out_dir), [Path(d) for d in ip_dirs])
    except Exception as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@slip.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("-ip", "--ip-dirs", multiple=True, type=click.Path(exists=True), help="IP source directories")
def check(file: str, ip_dirs: tuple[str, ...]):
    """Check a .slip file for errors without generating output."""
    from pathlib import Path
    from slip.cli._pipeline import run_check

    try:
        run_check(Path(file), [Path(d) for d in ip_dirs])
        click.echo("No errors found.")
    except Exception as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


def main():
    slip()
