import requests
from .database import SessionLocal
from .models import SystemModel, Branch


GENNIS_API = "https://admin.gennis.uz/api/base/locations"
TURON_API = "https://school.gennis.uz/api/Branch/branch_filtered/"


def _seed_branches(system_name: str, url: str, name_key: str, list_key: str = None):
    db = SessionLocal()
    try:
        system = db.query(SystemModel).filter(
            SystemModel.name == system_name,
            SystemModel.deleted == False,
        ).first()
        if not system:
            print(f"SystemModel '{system_name}' not found")
            return

        # Delete existing branches
        db.query(Branch).filter(Branch.system_model_id == system.id).delete()
        db.commit()

        data = requests.get(url).json()
        locations = data[list_key] if list_key else data

        created = 0
        for loc in locations:
            name = loc.get(name_key)
            if not name:
                continue
            db.add(Branch(name=name, system_model_id=system.id))
            created += 1

        db.commit()

        branches = db.query(Branch).filter(
            Branch.system_model_id == system.id,
            Branch.deleted == False,
        ).all()
        print(f"[{system_name}] created {created} branches:")
        for b in branches:
            print(f"  id={b.id}  name={b.name}")
    finally:
        db.close()


def seed_gennis_branches():
    _seed_branches("Gennis", GENNIS_API, name_key="name", list_key="locations")


def seed_turon_branches():
    _seed_branches("Turon", TURON_API, name_key="name")


def seed_all_branches():
    seed_gennis_branches()
    seed_turon_branches()


def seed_systems():
    db = SessionLocal()
    try:
        for name in ["Gennis", "Turon"]:
            exists = db.query(SystemModel).filter(SystemModel.name == name).first()
            if not exists:
                db.add(SystemModel(name=name, deleted=False))
                print(f"Created SystemModel: {name}")
            else:
                print(f"SystemModel already exists: {name}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed_systems()
    seed_all_branches()
