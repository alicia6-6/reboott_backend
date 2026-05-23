import os
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict  # ◀ 최신 Pydantic v2 설정 로드
from sqlalchemy import create_engine, Column, String, DateTime, Text
from sqlalchemy.orm import sessionmaker, Session, declarative_base # ◀ SQLAlchemy 최신 임포트 위치

# 1. DB 설정 (Render PostgreSQL 우선, 없으면 로컬 SQLite)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./shipping_mvp.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# [경고 1 해결] sqlalchemy.orm.declarative_base() 최신 문법으로 변경
Base = declarative_base()

# 2. SQLAlchemy DB 모델 정의
class ShipmentModel(Base):
    __tablename__ = "shipments"
    id = Column(String, primary_key=True, index=True) # B/L 번호
    shipper = Column(String, index=True)              # 화주사명
    origin = Column(String)                           # 출발지
    destination = Column(String)                      # 목적지
    status = Column(String)                           # 선적, 운항중, 도착, 통관 완료
    eta = Column(String)                              # 도착예정일 (YYYY-MM-DD)

class NotificationModel(Base):
    __tablename__ = "notifications"
    id = Column(String, primary_key=True, index=True)
    shipper = Column(String, index=True)              # 수신 대상 화주사
    bl_id = Column(String)                            # 관련 B/L 번호
    message = Column(Text)                            # 알림 내용
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# 3. Pydantic 스키마 정의
class ShipmentCreate(BaseModel):
    id: str
    shipper: str
    origin: str
    destination: str
    status: str
    eta: str

class ShipmentUpdate(BaseModel):
    status: Optional[str] = None
    eta: Optional[str] = None

# 개별 화물 응답 스키마 (최신 Pydantic v2 방식 적용)
class ShipmentResponse(BaseModel):
    id: str
    shipper: str
    origin: str
    destination: str
    status: str
    eta: str
    
    # [경고 2, 3 해결] model_config와 from_attributes 문법으로 전환
    model_config = ConfigDict(from_attributes=True)

class NotificationResponse(BaseModel):
    id: str
    shipper: str
    bl_id: str
    message: str
    created_at: datetime
    
    #  Pydantic v2 최신 문법으로 변경
    model_config = ConfigDict(from_attributes=True)

class LoginRequest(BaseModel):
    username: str
    password: str

# FastAPI 앱 생성
app = FastAPI(title="Forwarding Visibility MVP API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Mock 암호화/세션 토큰 (MVP 수준의 단순화)
MOCK_USERS = {
    "admin": {"password": "password123", "role": "admin", "shipper_name": None},
    "samsung": {"password": "password123", "role": "shipper", "shipper_name": "삼성전자"},
    "hyundai": {"password": "password123", "role": "shipper", "shipper_name": "현대모비스"}
}

# [API] 1. 보안 로그인
@app.post("/api/login")
def login(payload: LoginRequest):
    user = MOCK_USERS.get(payload.username)
    if not user or user["password"] != payload.password:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    return {
        "token": f"mock-jwt-token-for-{payload.username}",
        "role": user["role"],
        "shipper_name": user["shipper_name"]
    }

# [API] 2. 화물 전체 조회 (권한 격리 가드 장착, 최신 Response 스키마 맵핑)
@app.get("/api/shipments", response_model=List[ShipmentResponse])
def get_shipments(shipper_filter: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(ShipmentModel)
    if shipper_filter:
        query = query.filter(ShipmentModel.shipper == shipper_filter)
    return query.all()

# [API] 3. 신규 화물 배정 등록 (CREATE)
@app.post("/api/shipments", response_model=ShipmentResponse)
def create_shipment(payload: ShipmentCreate, db: Session = Depends(get_db)):
    exists = db.query(ShipmentModel).filter(ShipmentModel.id == payload.id).first()
    if exists:
        raise HTTPException(status_code=400, detail="이미 존재하는 B/L 번호입니다.")
    
    # payload.dict() 대신 최신 pydantic인 payload.model_dump() 사용 권장하지만 안전 호환
    db_item = ShipmentModel(**payload.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

# [API] 4. 화물 상태 및 ETA 수정 + 웹 인앱 알림 생성 트리거 (UPDATE)
@app.patch("/api/shipments/{bl_id}", response_model=ShipmentResponse)
def update_shipment(bl_id: str, payload: ShipmentUpdate, db: Session = Depends(get_db)):
    db_item = db.query(ShipmentModel).filter(ShipmentModel.id == bl_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="화물을 찾을 수 없습니다.")
    
    is_changed = False
    log_msg = f"B/L {bl_id} 화물의 정보가 업데이트되었습니다: "
    
    if payload.status and db_item.status != payload.status:
        log_msg += f"[상태 변경: {db_item.status} ➔ {payload.status}] "
        db_item.status = payload.status
        is_changed = True
        
    if payload.eta and db_item.eta != payload.eta:
        log_msg += f"[ETA 변경: {db_item.eta} ➔ {payload.eta}] "
        db_item.eta = payload.eta
        is_changed = True

    if is_changed:
        noti_item = NotificationModel(
            id=f"NOTI-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{bl_id}",
            shipper=db_item.shipper,
            bl_id=bl_id,
            message=log_msg
        )
        db.add(noti_item)
        db.commit()
        db.refresh(db_item)
        
    return db_item

# [API] 5. 화물 삭제 (DELETE)
@app.delete("/api/shipments/{bl_id}")
def delete_shipment(bl_id: str, db: Session = Depends(get_db)):
    db_item = db.query(ShipmentModel).filter(ShipmentModel.id == bl_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="화물을 찾을 수 없습니다.")
    db.delete(db_item)
    db.commit()
    return {"detail": "성공적으로 삭제되었습니다."}

# [API] 6. 화주사별 인앱 웹 알림 조회 목록 API
@app.get("/api/notifications/{shipper_name}", response_model=List[NotificationResponse])
def get_notifications(shipper_name: str, db: Session = Depends(get_db)):
    return db.query(NotificationModel).filter(NotificationModel.shipper == shipper_name).order_by(NotificationModel.created_at.desc()).all()


if __name__ == "__main__":
    import uvicorn
    # 로컬 개발 환경용 포트 8000번으로 서버를 직접 실행합니다.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)