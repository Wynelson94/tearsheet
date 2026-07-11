"""Every MCP tool must have a CLI subcommand (the `search` gap class of bug)."""

from fastmcp import Client

from tearsheet import server
from tearsheet.cli import build_parser

CLI_ONLY_ALLOWED = {"cache"}  # local housekeeping has no MCP equivalent on purpose


async def test_every_mcp_tool_has_a_cli_subcommand() -> None:
    async with Client(server.mcp) as client:
        tool_names = {t.name for t in await client.list_tools()}

    parser = build_parser()
    subparsers = next(
        a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"
    )
    cli_commands = set(subparsers.choices.keys())

    missing_from_cli = tool_names - cli_commands
    assert not missing_from_cli, f"MCP tools with no CLI subcommand: {missing_from_cli}"

    unexpected_cli_only = cli_commands - tool_names - CLI_ONLY_ALLOWED
    assert not unexpected_cli_only, (
        f"CLI subcommands with no MCP tool (add to MCP or to CLI_ONLY_ALLOWED): "
        f"{unexpected_cli_only}"
    )
