def register_routes(app):
    from app.routes import auth, users, trips, itineraries, groups, expenses, chat, weather, notifications, storage, wishlists
    for module in (auth, users, trips, itineraries, groups, expenses, chat, weather, notifications, storage, wishlists):
        app.register_blueprint(module.bp, url_prefix="/api")
