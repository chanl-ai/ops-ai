"""A plugin for tools-service's paging tests: data tools that page by link, token and offset, and one whose query is
built from checked inputs."""

from ops_plugin_sdk import Plugin

plugin = Plugin.beside(__file__)
