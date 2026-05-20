from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Literal, Optional
import os

# 💾 SQL Alchemy (DB 연동 라이브러리) 임포트
from sqlalchemy import create_engine, Column, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# 🔌 1. 데이터베이스 연결 설정
# Render 클라우드가 제공하는 환경변수(DATABASE_URL)를 가져옵니다.
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    # SQLAlchemy 표준에 맞게 postgresql:// 로 변환해 줍니다.
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    # 환경변수가 없을 때 로컬 테스트용으로 사용할 sqlite 파일 DB입니다.
    DATABASE_URL = "sqlite:///./local_test.db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 🗂️ 2. 데이터베이스 테이블(ORM) 정의
class ShipmentModel(Base):
    __tablename__ = "shipments"

    id = Column(String, primary_key=True, index=True) # B/L 번호
    shipper = Column(String, nullable=False)          # 화주 명
    origin = Column(String, nullable=False)           # 출발지
    destination = Column(String, nullable=False)      # 목적지
    status = Column(String, nullable=False)           # 현재 상태
    eta = Column(String, nullable=False)              # 도착 예정일

# 서버 시작 시 테이블이 없으면 자동으로 생성해 줍니다.
Base.metadata.create_all(bind=engine)

# 🚀 초기 데이터 마이그레이션 (DB가 완전히 비어있을 때만 샘플 데이터 3건 주입)
def init_db():
    db = SessionLocal()
    try:
        if db.query(ShipmentModel).count() == 0:
            initial_data = [
                ShipmentModel(id="BL-2026-001", shipper="삼성전자", origin="부산 (PUS)", destination="로스앤젤레스 (LAX)", status="운항중", eta="2026-05-25"),
                ShipmentModel(id="BL-2026-002", shipper="삼성전자", origin="상하이 (SHA)", destination="부산 (PUS)", status="선적", eta="2026-05-28"),
                ShipmentModel(id="BL-2026-003", shipper="현대모비스", origin="부산 (PUS)", destination="로테르담 (RTM)", status="도착", eta="2026-05-19"),
            ]
            db.add_all(initial_data)
            db.commit()
    finally:
        db.close()

init_db()

# 🌐 3. FastAPI 인스턴스 및 CORS 설정
app = FastAPI(title="Forwarding Visibility MVP API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- [Pydantic 스키마] 데이터 검증 모델 정의 ---
ShipmentStatus = Literal['선적', '운항중', '도착', '통관 완료']

class Shipment(BaseModel):
    id: str
    shipper: str
    origin: str
    destination: str
    status: ShipmentStatus
    eta: str
    class Config:
        orm_mode = True

class CreateShipmentInput(BaseModel):
    id: str
    shipper: str
    origin: str
    destination: str
    status: ShipmentStatus
    eta: str

class UpdateShipmentInput(BaseModel):
    status: ShipmentStatus
    eta: str

class LoginInput(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    success: bool
    token: str
    role: Literal['shipper', 'admin']
    shipper_name: Optional[str] = None

# DB 세션을 관리하는 의존성 주입 함수
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

NOTIFICATION_LOGS = []

# --- [API 엔드포인트 구현] ---

@app.post("/api/login", response_model=LoginResponse)
def login(data: LoginInput):
    if data.username == "shipper" and data.password == "password123":
        return {"success": True, "token": "mock-jwt-token-shipper-value", "role": "shipper", "shipper_name": "삼성전자"}
    elif data.username == "admin" and data.password == "password123":
        return {"success": True, "token": "mock-jwt-token-admin-value", "role": "admin"}
    raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 일치하지 않습니다.")

@app.get("/api/shipments", response_model=List[Shipment])
def get_shipments(db: Session = Depends(get_db)):
    """[조회 - READ] DB 테이블의 전체 화물 목록 조회"""
    return db.query(ShipmentModel).all()

@app.post("/api/shipments", response_model=Shipment)
def create_shipment(data: CreateShipmentInput, db: Session = Depends(get_db)):
    """[생성 - CREATE] DB 테이블에 새 화물 등록"""
    db_exist = db.query(ShipmentModel).filter(ShipmentModel.id == data.id).first()
    if db_exist:
        raise HTTPException(status_code=400, detail="이미 존재하는 B/L 번호입니다.")
    
    new_cargo = ShipmentModel(
        id=data.id, shipper=data.shipper, origin=data.origin,
        destination=data.destination, status=data.status, eta=data.eta
    )
    db.add(new_cargo)
    db.commit()
    db.refresh(new_cargo)
    return new_cargo

@app.patch("/api/shipments/{shipment_id}", response_model=Shipment)
def update_shipment(shipment_id: str, data: UpdateShipmentInput, db: Session = Depends(get_db)):
    """[수정 - UPDATE] DB 테이블의 화물 상태 및 ETA 업데이트"""
    shipment = db.query(ShipmentModel).filter(ShipmentModel.id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="해당 화물 데이터를 찾을 수 없습니다.")
        
    if shipment.eta != data.eta:
        log_msg = f"[알림] {shipment_id} 화물의 ETA가 {shipment.eta}에서 {data.eta}로 변경되었습니다."
        NOTIFICATION_LOGS.append({"shipment_id": shipment_id, "message": log_msg})
    
    shipment.status = data.status
    shipment.eta = data.eta
    db.commit()
    db.refresh(shipment)
    return shipment

@app.delete("/api/shipments/{shipment_id}")
def delete_shipment(shipment_id: str, db: Session = Depends(get_db)):
    """[삭제 - DELETE] DB 테이블에서 화물 삭제"""
    shipment = db.query(ShipmentModel).filter(ShipmentModel.id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="해당 화물 데이터를 찾을 수 없습니다.")
    
    db.delete(shipment)
    db.commit()
    return {"success": True, "message": f"{shipment_id} 화물이 정상적으로 삭제되었습니다."}

@app.get("/api/notifications")
def get_notifications():
    return NOTIFICATION_LOGS

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)