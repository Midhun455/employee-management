# main.py
from fastapi import FastAPI, HTTPException, Query, Path, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import csv, io

# using sqlite for now
DATABASE_URL = "sqlite:///./employees.db"

# --- DB setup ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class EmployeeORM(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    email = Column(String, nullable=False, unique=True, index=True)
    age = Column(Integer, nullable=False)
    department = Column(String, nullable=False, index=True)


Base.metadata.create_all(bind=engine)


# --- Pydantic stuff ---
class EmployeeCreate(BaseModel):
    name: str = Field(..., min_length=1, example="Alice")
    email: EmailStr = Field(..., example="alice@example.com")
    age: int = Field(..., ge=18, le=100, example=30)
    department: str = Field(..., min_length=1, example="Engineering")


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    age: Optional[int] = None
    department: Optional[str] = None


class EmployeeOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    age: int
    department: str

    class Config:
        from_attributes = True


app = FastAPI(title="Employee Management API", version="1.0")


# --- utils ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_employee(db: Session, emp_id: int):
    return db.query(EmployeeORM).filter(EmployeeORM.id == emp_id).first()


def apply_filters(query, dept=None, search=None):
    if dept:
        query = query.filter(EmployeeORM.department == dept)
    if search:
        query = query.filter(EmployeeORM.name.ilike(f"%{search}%"))
    return query


# --- routes ---


@app.post("/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(payload: EmployeeCreate):
    db = SessionLocal()
    try:
        # check duplicate email
        if db.query(EmployeeORM).filter(EmployeeORM.email == payload.email).first():
            raise HTTPException(status_code=400, detail="Email already exists.")
        emp = EmployeeORM(
            name=payload.name.strip(),
            email=payload.email,
            age=payload.age,
            department=payload.department.strip(),
        )
        db.add(emp)
        db.commit()
        db.refresh(emp)
        return emp
    finally:
        db.close()


@app.get("/employees", response_model=List[EmployeeOut])
def list_employees(
    dept: Optional[str] = Query(None, description="Filter by department"),
    search: Optional[str] = Query(None, description="Search by name"),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
):
    db = SessionLocal()
    try:
        q = db.query(EmployeeORM)

        if dept:
            q = q.filter(EmployeeORM.department == dept)
        if search:
            q = q.filter(EmployeeORM.name.ilike(f"%{search}%"))

        q = q.offset((page - 1) * per_page).limit(per_page)
        return q.all()
    finally:
        db.close()


@app.put("/employees/{id}", response_model=EmployeeOut)
def update_employee(id: int, payload: EmployeeUpdate):
    db = SessionLocal()
    try:
        emp = get_employee(db, id)
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found")

        # check email if changed
        if payload.email and payload.email != emp.email:
            exists = (
                db.query(EmployeeORM).filter(EmployeeORM.email == payload.email).first()
            )
            if exists:
                raise HTTPException(status_code=400, detail="Email already in use.")

        # update fields
        if payload.name:
            emp.name = payload.name.strip()
        if payload.email:
            emp.email = payload.email
        if payload.age:
            emp.age = payload.age
        if payload.department:
            emp.department = payload.department.strip()

        db.commit()
        db.refresh(emp)
        return emp
    finally:
        db.close()


@app.delete("/employees/{id}", status_code=200)
def delete_employee(id: int):
    db = SessionLocal()
    try:
        emp = db.query(EmployeeORM).filter(EmployeeORM.id == id).first()
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found")
        db.delete(emp)
        db.commit()
        return {"message": "Employee deleted successfully"}
    finally:
        db.close()


@app.get("/employees/export")
def export_employees(
    fmt: str = Query("csv", regex="^(csv|json)$"),
    dept: Optional[str] = None,
    search: Optional[str] = None,
):
    db = SessionLocal()
    try:
        q = db.query(EmployeeORM)

        if dept:
            q = q.filter(EmployeeORM.department == dept)
        if search:
            q = q.filter(EmployeeORM.name.contains(search))

        rows = q.all()

        if fmt == "json":
            return [EmployeeOut.model_validate(r).dict() for r in rows]

        # CSV export
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "name", "email", "age", "department"])
        for r in rows:
            writer.writerow([r.id, r.name, r.email, r.age, r.department])

        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=employees.csv"},
        )
    finally:
        db.close()


@app.get("/")
def root():
    return {"msg": "Employee API up. Check /docs for Swagger UI."}
