from fastapi import FastAPI

from server.routes import conversations, generations, resources


def register_routes(app: FastAPI):
    app.include_router(resources.router)
    app.include_router(conversations.router)
    app.include_router(generations.router)
