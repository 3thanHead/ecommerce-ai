"""The API surface, one module per route group:

    health.py    GET /health
    agents.py    /api/agents/* + /ws/agents/{name}
    blog.py      /shop + /blog + /store/export
    chat.py      GET / (the chat console) + /api/models + /ws/chat

Each module owns everything for its surface and exports `router`; main.py
just mounts them.
"""
from . import agents, blog, chat, health

routers = [health.router, agents.router, blog.router, chat.router]
