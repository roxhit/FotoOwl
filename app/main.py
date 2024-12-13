from fastapi import FastAPI
from app.routes.router import *
from app.config.db import Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.include_router(router)
