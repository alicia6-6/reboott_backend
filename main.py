from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Literal, Optional
import os

# 💾 SQL Alchemy (DB 연동 라이브러리) 임포트
from sqlalchemy import create_engine, Column, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 🔌 1. 데이터베이스 연결 설정
# Render 클라우드가 제공하는 환경변수(DATABASE_URL)를 쓰고, 로컬 테스트용 sqlite 백업을 둡니다.
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    # SQLAlchemy는 postgres:// 대신 postgresql:// 로 시작해야 인식을 합니다.
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    # 환경변수가 없으면 임시로 로컬에 sqlite 파일 DB를 생성해 테스트합니다.
    DATABASE_URL = "sqlite:///./local_test.db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 🗂️ 2. 데이터베이스 테이블(OR Mapping) 정의
class ShipmentModel(Base):
    __tablename__ = "shipments"

    id = Column(String, primary_key=True, index=True)
    shipper = Column(String, nullable=False)
    origin = Column(String, nullable=False)
    destination = Column(String, nullable=False)
    status = Column(String, nullable=False)
    eta = Column(String, nullable=False)

# 서버 시작 시 테이블이 없으면 자동 생성
Base.metadata.create_all(bind=engine)

# 🚀 초기 데이터 마이그레이션 (DB가 텅 빌었을 때만 초기값 3건 강제 주입)
db = SessionLocal()
if db.query(ShipmentModel).count() == 0:
    initial_data = [
        ShipmentModel(id="BL-2026-001", shipper="삼성전자", origin="부산 (PUS)", destination="로스앤젤레스 (LAX)", status="운항중", eta="2026-05-25"),
        ShipmentModel(id="BL-2026-002", shipper="삼성전자", origin="상하이 (SHA)", destination="부산 (PUS)", status="선적", eta="2026-05-28"),
        ShipmentModel(id="BL-2026-003", shipper="현대모비스", origin="부산 (PUS)", destination="로테르담 (RTM)", status="도착", eta="2026-05-19"),
    ]
    db.add_all(initial_data)
    db.commit()
db.close()


# 🌐 3. FastAPI 인스턴스 및 CORS 앱 설정
app = FastAPI(title="Forwarding Visibility MVP API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- [스키마] 데이터 모델 정의 ---
ShipmentStatus = Literal['선적', '운항중', '도착', '통관 완료']

class Shipment(BaseModel):
    id: str
    shipper: str
    origin: str
    destination: str
    status: ShipmentStatus
    eta: str
    class Config:
        orm_mode = True # SQLAlchemy 모델 객체를 Pydantic이 알아서 변환하게 허용

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

NOTIFICATION_LOGS = []

# --- [API] 엔드포인트 구현 ---

@app.post("/api/login", response_model=LoginResponse)
def login(data: LoginInput):
    if data.username == "shipper" and data.password == "password123":
        return {"success": True, "token": "mock-jwt-token-shipper-value", "role": "shipper", "shipper_name": "삼성전자"}
    elif data.username == "admin" and data.password == "password123":
        return {"success": True, "token": "mock-jwt-token-admin-value", "role": "admin"}
    raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 일치하지 않습니다.")

@app.get("/api/shipments", response_model=List[Shipment])
def get_shipments():
    """메모리가 아닌 진짜 DB 테이블에서 화물 목록 전건 조회"""
    db = SessionLocal()
    shipments = db.query(ShipmentModel).all()
    db.close()
    return shipments

@app.patch("/api/shipments/{shipment_id}", response_model=Shipment)
def update_shipment(shipment_id: str, data: UpdateShipmentInput):
    """운영팀의 화물 상태 및 ETA를 실제 DB에 업데이트 영구 반영"""
    db = SessionLocal()
    shipment = db.query(ShipmentModel).filter(ShipmentModel.id == shipment_id).first()
    
    if not shipment:
        db.close()
        raise HTTPException(status_code=404, detail="해당 화물 데이터를 찾을 수 없습니다.")
        
    # 비즈니스 로직: ETA 변경 로그 생성
    if shipment.eta != data.eta:
        log_msg = f"[알림] {shipment_id} 화물의 ETA가 {shipment.eta}에서 {data.eta}로 변경되었습니다."
        NOTIFICATION_LOGS.append({"shipment_id": shipment_id, "message": log_msg})
    
    # DB 필드 값 수정 및 반영
    shipment.status = data.status
    shipment.eta = data.eta
    db.commit()
    db.refresh(shipment)
    db.close()
    return shipment

@app.get("/api/notifications")
def get_notifications():
    return NOTIFICATION_LOGS

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)