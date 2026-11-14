
from app.core.database import Base, engine

# Import models so SQLAlchemy registers their tables
from app.core import models

def initialize_database():
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully!")

    print("Created tables:")
    for table in Base.metadata.sorted_tables:
        print(f"- {table.name}")


if __name__ == "__main__":
    initialize_database()
