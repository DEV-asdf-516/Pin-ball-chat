from fastapi import FastAPI

from server.routes import characters, conversations, generations, health, models, plots, preferences, user_profiles


def register_routes(app: FastAPI):
    app.include_router(health.router)
    app.include_router(characters.router)
    app.include_router(user_profiles.router)
    app.include_router(plots.router)
    app.include_router(preferences.router)
    app.include_router(conversations.router)
    app.include_router(generations.router)
    app.include_router(models.router)
