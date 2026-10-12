"""Inbound channels: each turns what arrives (mail, widget messages, API calls) into find-or-create thread and run
calls. A channel is configured as a Deployment: this graph, on this channel, with these settings. The graph never
knows which channel woke it."""
