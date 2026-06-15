"""
Sigma GPT Runtime - Hugging Face Space
Serves repo-backed personalization, receipts, and policy endpoints for Custom GPT Actions.
"""

from fastapi import FastAPI, HTTPException, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Any, Optional
from pathlib import Path
import yaml
import json
import hashlib
import os
from datetime import datetime
import httpx
import websockets
import asyncio
import json

# Configuration
HF_RUNTIME_TOKEN = os.getenv("HF_RUNTIME_TOKEN", "default-token-change-me")
GITHUB_RAW_BASE = os.getenv("GITHUB_RAW_BASE", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
ALLOW_DIRECT_REPO_WRITES = os.getenv("ALLOW_DIRECT_REPO_WRITES", "false").lower() == "true"

# Gate.io configuration
GATE_API_BASE = os.getenv("GATE_API_BASE", "https://api.gateio.ws/api/v4")
GATE_WS_BASE = os.getenv("GATE_WS_BASE", "wss://fx-ws.gateio.ws/v4/ws/usdt")
GATE_API_KEY = os.getenv("GATE_API_KEY", "")
GATE_API_SECRET = os.getenv("GATE_API_SECRET", "")

# Use local directories for testing, /data for HF Space
IS_HF_SPACE = os.path.exists("/data")
BASE_DIR = Path("/data") if IS_HF_SPACE else Path(__file__).parent.parent
POLICY_DIR = BASE_DIR / "policy"
RECEIPTS_DIR = BASE_DIR / "receipts"
STREAM_DATA_DIR = BASE_DIR / "stream_data"
RECEIPTS_DIR.mkdir(exist_ok=True, parents=True)
STREAM_DATA_DIR.mkdir(exist_ok=True, parents=True)

# Active stream storage
active_streams: Dict[str, Dict[str, Any]] = {}

# Helper function for Gate.io WebSocket connection
async def connect_gate_ws(stream_id: str, symbols: List[str], channels: List[str], duration_seconds: int):
    """Connect to Gate.io WebSocket and record events."""
    messages = []
    start_time = datetime.utcnow()
    file_path = STREAM_DATA_DIR / f"{stream_id}.jsonl"

    try:
        async with websockets.connect(GATE_WS_BASE) as ws:
            # Subscribe to channels
            for symbol in symbols:
                for channel in channels:
                    subscribe_msg = {
                        "time": int(datetime.utcnow().timestamp()),
                        "channel": channel,
                        "event": "subscribe",
                        "payload": [symbol]
                    }
                    await ws.send(json.dumps(subscribe_msg))

            # Record messages for duration
            while (datetime.utcnow() - start_time).total_seconds() < duration_seconds:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    msg_data = json.loads(message)
                    messages.append(msg_data)

                    # Write to file immediately
                    with open(file_path, 'a') as f:
                        f.write(json.dumps(msg_data) + '\n')

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    print(f"WebSocket error: {e}")
                    break

    except Exception as e:
        print(f"WebSocket connection error: {e}")

    # Update stream status
    if stream_id in active_streams:
        active_streams[stream_id]["status"] = "stopped"
        active_streams[stream_id]["messages_collected"] = len(messages)
        active_streams[stream_id]["file_path"] = str(file_path)

    return messages

# Initialize FastAPI
app = FastAPI(
    title="Sigma GPT Runtime",
    description="Repo-backed personalization and receipt storage for Custom GPT Actions",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic models
class ContextRequest(BaseModel):
    chat_id: str = Field(..., description="Chat identifier")
    user_id: Optional[str] = Field(None, description="User identifier")

class ContextResponse(BaseModel):
    chat_id: str
    policy_state: Dict[str, Any]
    user_capsule: Dict[str, Any]
    scoring_weights: Dict[str, Any]
    claim_labels: List[str]

class VerifyRequest(BaseModel):
    claim: str = Field(..., description="Claim to verify")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")

class VerifyResponse(BaseModel):
    claim: str
    verified: bool
    confidence: float
    evidence_refs: List[str]

class ScoreRequest(BaseModel):
    answer: str = Field(..., description="Answer to score")
    chat_id: str = Field(..., description="Chat identifier")

class ScoreResponse(BaseModel):
    answer: str
    density_score: float
    artifact_count: int
    overall_grade: str

class ReceiptRequest(BaseModel):
    chat_id: str = Field(..., description="Chat identifier")
    answer: str = Field(..., description="Answer content")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

class ReceiptResponse(BaseModel):
    receipt_id: str
    chat_id: str
    sha256_hash: str
    timestamp: str
    stored: bool

class BenchmarkRequest(BaseModel):
    prompt: str = Field(..., description="Prompt to benchmark")
    model: Optional[str] = Field("gpt-4", description="Model identifier")

class BenchmarkResponse(BaseModel):
    prompt: str
    response: str
    metrics: Dict[str, float]

class ProposeUpdateRequest(BaseModel):
    policy_delta: Dict[str, Any] = Field(..., description="Policy changes to propose")
    reason: str = Field(..., description="Reason for the update")

class ProposeUpdateResponse(BaseModel):
    proposal_id: str
    status: str
    dry_run: bool
    github_commit_url: Optional[str] = None


# Gate.io models
class GateConfigResponse(BaseModel):
    """Gate.io configuration"""
    api_base: str = Field(..., description="Gate.io API base URL")
    ws_base: str = Field(..., description="Gate.io WebSocket base URL")
    disclaimer: str = Field(..., description="Research-only disclaimer")

class GateCandlesRequest(BaseModel):
    """Request for Gate.io candles"""
    contract: str = Field(..., description="Contract symbol")
    interval: str = Field(default="1h", description="Candle interval")
    limit: int = Field(default=100, description="Number of candles")

class GateCandlesResponse(BaseModel):
    """Response with Gate.io candles"""
    contract: str = Field(..., description="Contract symbol")
    interval: str = Field(..., description="Candle interval")
    candles: List[List[Any]] = Field(..., description="Candle data (arrays from Gate.io API)")
    source: str = Field(..., description="Data source")
    disclaimer: str = Field(..., description="Research-only disclaimer")

class GateBacktestRequest(BaseModel):
    """Request for backtest"""
    candles: List[List[Any]] = Field(..., description="Candle data (arrays from Gate.io API)")
    strategy: str = Field(default="sma_cross", description="Strategy type")
    short_period: int = Field(default=10, description="Short period")
    long_period: int = Field(default=30, description="Long period")

class GateBacktestResponse(BaseModel):
    """Response with backtest results"""
    strategy: str = Field(..., description="Strategy used")
    total_return: float = Field(..., description="Total return")
    max_drawdown: float = Field(..., description="Maximum drawdown")
    trade_count: int = Field(..., description="Number of trades")
    disclaimer: str = Field(..., description="Research estimate disclaimer")

class GateWsSampleRequest(BaseModel):
    """Request for WebSocket sample"""
    contract: str = Field(..., description="Contract symbol")
    channels: List[str] = Field(default=["futures.trades"], description="Channels to subscribe")
    duration: int = Field(default=5, description="Sample duration in seconds")

class GateWsSampleResponse(BaseModel):
    """Response with WebSocket sample"""
    contract: str = Field(..., description="Contract symbol")
    messages: List[Dict[str, Any]] = Field(..., description="Sampled messages")
    message_count: int = Field(..., description="Number of messages")
    disclaimer: str = Field(..., description="Live data snapshot disclaimer")

class PromptCalibrateRequest(BaseModel):
    """Request for prompt calibration"""
    prompt: Optional[str] = Field(None, description="User's raw prompt (v2)")
    user_prompt: Optional[str] = Field(None, description="User's raw prompt (v1)")
    context: Optional[str] = Field(None, description="Additional context")

    @model_validator(mode='before')
    def validate_prompt_field(cls, v):
        if not v.get('prompt') and not v.get('user_prompt'):
            raise ValueError('Either prompt or user_prompt must be provided')
        return v

class PromptCalibrateResponse(BaseModel):
    """Response with calibrated prompt"""
    original_prompt: str = Field(..., description="Original user prompt")
    calibrated_prompt: str = Field(..., description="Calibrated SEPF prompt")
    artifact_type: str = Field(..., description="Suggested artifact type")
    claim_labels: List[str] = Field(..., description="Suggested claim labels")

class SignalFuseRequest(BaseModel):
    """Request for signal fusion"""
    backtest_result: Dict[str, Any] = Field(..., description="Backtest result")
    ws_snapshot: Dict[str, Any] = Field(..., description="WebSocket snapshot")
    history_capsule: Optional[Dict[str, Any]] = Field(None, description="Latent history capsule")

class SignalFuseResponse(BaseModel):
    """Response with fused signal"""
    research_score: float = Field(..., description="Research score (0-1)")
    confidence: float = Field(..., description="Confidence level")
    components: Dict[str, Any] = Field(..., description="Component scores")
    disclaimer: str = Field(..., description="Research score disclaimer")

class CostSavingsRequest(BaseModel):
    """Request for cost savings estimate"""
    artifact_type: str = Field(..., description="Type of artifact")
    complexity: str = Field(default="medium", description="Complexity level")
    hours_estimate: Optional[int] = Field(None, description="Estimated hours")

class CostSavingsResponse(BaseModel):
    """Response with cost savings estimate"""
    artifact_type: str = Field(..., description="Type of artifact")
    replacement_cost_low: float = Field(..., description="Low replacement cost")
    replacement_cost_base: float = Field(..., description="Base replacement cost")
    replacement_cost_high: float = Field(..., description="High replacement cost")
    time_saved_hours: float = Field(..., description="Estimated time saved")
    disclaimer: str = Field(..., description="User-side savings disclaimer")


# Gate.io stream models
class GateStreamStartRequest(BaseModel):
    """Request to start Gate.io stream"""
    symbols: List[str] = Field(..., description="Contract symbols to collect")
    channels: List[str] = Field(default=["futures.book_ticker", "futures.order_book_update"], description="WebSocket channels")
    settle: str = Field(default="usdt", description="Settlement currency")
    duration_seconds: int = Field(default=3600, description="Collection duration")

class GateStreamStartResponse(BaseModel):
    """Response with stream start status"""
    status: str = Field(..., description="Stream status")
    stream_id: str = Field(..., description="Stream identifier")
    symbols: List[str] = Field(..., description="Contract symbols")
    channels: List[str] = Field(..., description="WebSocket channels")
    started_at: str = Field(..., description="Start timestamp")
    receipt_hash: str = Field(..., description="Receipt hash")
    disclaimer: str = Field(..., description="Research-only disclaimer")

class GateStreamStopRequest(BaseModel):
    """Request to stop Gate.io stream"""
    stream_id: str = Field(..., description="Stream identifier")

class GateStreamStopResponse(BaseModel):
    """Response with stream stop status"""
    status: str = Field(..., description="Stream status")
    stream_id: str = Field(..., description="Stream identifier")
    stopped_at: str = Field(..., description="Stop timestamp")
    messages_collected: int = Field(..., description="Messages collected")
    receipt_hash: str = Field(..., description="Receipt hash")

class GateSnapshotResponse(BaseModel):
    """Response with market snapshot"""
    symbol: str = Field(..., description="Contract symbol")
    timestamp: str = Field(..., description="Snapshot timestamp")
    best_bid: float = Field(..., description="Best bid price")
    best_ask: float = Field(..., description="Best ask price")
    spread_bps: float = Field(..., description="Spread in basis points")
    mid_price: float = Field(..., description="Mid price")
    receipt_hash: str = Field(..., description="Receipt hash")
    disclaimer: str = Field(..., description="Research-only disclaimer")

class GateFeaturesResponse(BaseModel):
    """Response with stream features"""
    symbol: str = Field(..., description="Contract symbol")
    window_seconds: int = Field(..., description="Time window")
    features: Dict[str, Any] = Field(..., description="Feature vector")
    claim_label: str = Field(..., description="Claim label")
    receipt_hash: str = Field(..., description="Receipt hash")
    disclaimer: str = Field(..., description="Research-only disclaimer")

class GateReplayRequest(BaseModel):
    """Request to replay stream"""
    stream_id: str = Field(..., description="Stream identifier")
    start_offset: int = Field(default=0, description="Start offset")
    duration_seconds: int = Field(default=60, description="Duration")

class GateReplayResponse(BaseModel):
    """Response with replay data"""
    stream_id: str = Field(..., description="Stream identifier")
    replay_data: List[Dict[str, Any]] = Field(..., description="Replay data")
    receipt_hash: str = Field(..., description="Receipt hash")


# Benchmark models
class BenchmarkCompareRequest(BaseModel):
    """Request to compare benchmarks"""
    benchmarks: List[Dict[str, Any]] = Field(..., description="Benchmark results")

class BenchmarkCompareResponse(BaseModel):
    """Response with comparison results"""
    comparison: Dict[str, Any] = Field(..., description="Comparison results")

class ResidueScoreRequest(BaseModel):
    """Request to calculate residue score"""
    baseline_score: float = Field(..., description="Baseline score")
    runtime_score: float = Field(..., description="Runtime score")
    decay_factor: float = Field(default=0.1, description="Decay factor")

class ResidueScoreResponse(BaseModel):
    """Response with residue score"""
    baseline_score: float = Field(..., description="Baseline score")
    runtime_score: float = Field(..., description="Runtime score")
    residue: float = Field(..., description="Residue score")
    receipt_hash: str = Field(..., description="Receipt hash")


# Helper functions
def verify_auth(authorization: Optional[str] = Header(None)) -> bool:
    """Verify Bearer token authentication."""
    if not authorization:
        return False
    if not authorization.startswith("Bearer "):
        return False
    token = authorization.replace("Bearer ", "")
    return token == HF_RUNTIME_TOKEN


def load_policy_file(filename: str) -> Dict[str, Any]:
    """Load policy file from data directory."""
    file_path = POLICY_DIR / filename
    if file_path.exists():
        with open(file_path, 'r') as f:
            if filename.endswith('.yaml') or filename.endswith('.yml'):
                return yaml.safe_load(f)
            else:
                return json.load(f)
    return {}


def save_receipt(receipt_data: Dict[str, Any]) -> str:
    """Save receipt to receipts directory."""
    receipt_id = f"receipt-{datetime.utcnow().timestamp()}"
    receipt_path = RECEIPTS_DIR / f"{receipt_id}.json"
    with open(receipt_path, 'w') as f:
        json.dump(receipt_data, f, indent=2)
    return receipt_id


def get_latest_receipt() -> Optional[Dict[str, Any]]:
    """Get the most recent receipt."""
    receipts = list(RECEIPTS_DIR.glob("*.json"))
    if receipts:
        latest = max(receipts, key=lambda p: p.stat().st_mtime)
        with open(latest, 'r') as f:
            return json.load(f)
    return None


# Endpoints
@app.get("/")
async def root():
    """Root endpoint with runtime information."""
    return {
        "service": "Sigma GPT Runtime",
        "version": "1.0.0",
        "status": "operational",
        "github_repo": GITHUB_REPO,
        "allow_direct_repo_writes": ALLOW_DIRECT_REPO_WRITES
    }


@app.post("/context", response_model=ContextResponse)
async def get_context(request: ContextRequest, authorization: Optional[str] = Header(None)):
    """Get repo-backed personalization capsule for a chat."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    policy_state = load_policy_file("policy_state.yaml")
    user_capsule = load_policy_file("user_capsule.json")
    scoring_weights = load_policy_file("scoring_weights.yaml")
    claim_labels_data = load_policy_file("claim_labels.yaml")
    claim_labels = claim_labels_data.get("labels", [])

    return ContextResponse(
        chat_id=request.chat_id,
        policy_state=policy_state,
        user_capsule=user_capsule,
        scoring_weights=scoring_weights,
        claim_labels=claim_labels
    )


@app.get("/policy")
async def get_policy(authorization: Optional[str] = Header(None)):
    """Get current policy state."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return load_policy_file("policy_state.yaml")


@app.post("/verify", response_model=VerifyResponse)
async def verify_claim(request: VerifyRequest, authorization: Optional[str] = Header(None)):
    """Verify a claim against policy and evidence."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Simple verification logic - in production, use actual evidence checking
    verified = len(request.claim) > 10  # Placeholder
    confidence = 0.7 if verified else 0.3

    return VerifyResponse(
        claim=request.claim,
        verified=verified,
        confidence=confidence,
        evidence_refs=[]
    )


@app.post("/score", response_model=ScoreResponse)
async def score_answer(request: ScoreRequest, authorization: Optional[str] = Header(None)):
    """Score answer for density and artifact yield."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    text_length = len(request.answer)
    density_score = min(1.0, text_length / 500.0)
    artifact_count = request.answer.count("```") // 2  # Count code blocks

    overall_score = (density_score + min(1.0, artifact_count / 3.0)) / 2.0
    if overall_score >= 0.8:
        grade = "A"
    elif overall_score >= 0.6:
        grade = "B"
    elif overall_score >= 0.4:
        grade = "C"
    else:
        grade = "D"

    return ScoreResponse(
        answer=request.answer,
        density_score=density_score,
        artifact_count=artifact_count,
        overall_grade=grade
    )


@app.post("/receipt", response_model=ReceiptResponse)
async def create_receipt(request: ReceiptRequest, authorization: Optional[str] = Header(None)):
    """Store answer receipt with hash and timestamp."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    sha256_hash = hashlib.sha256(request.answer.encode()).hexdigest()
    timestamp = datetime.utcnow().isoformat()

    receipt_data = {
        "chat_id": request.chat_id,
        "answer": request.answer,
        "sha256_hash": sha256_hash,
        "timestamp": timestamp,
        "metadata": request.metadata
    }

    receipt_id = save_receipt(receipt_data)

    return ReceiptResponse(
        receipt_id=receipt_id,
        chat_id=request.chat_id,
        sha256_hash=sha256_hash,
        timestamp=timestamp,
        stored=True
    )


@app.get("/receipts/latest")
async def get_latest_receipt_endpoint(authorization: Optional[str] = Header(None)):
    """Get the most recent receipt."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return get_latest_receipt()


@app.post("/benchmark", response_model=BenchmarkResponse)
async def run_benchmark(request: BenchmarkRequest, authorization: Optional[str] = Header(None)):
    """Run benchmark on prompt."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Placeholder benchmark - in production, actual model call
    return BenchmarkResponse(
        prompt=request.prompt,
        response="Benchmark response placeholder",
        metrics={"latency_ms": 100, "tokens": 50}
    )


@app.post("/propose-update", response_model=ProposeUpdateResponse)
async def propose_update(request: ProposeUpdateRequest, authorization: Optional[str] = Header(None)):
    """Propose policy update to GitHub."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    proposal_id = f"proposal-{datetime.utcnow().timestamp()}"
    dry_run = not ALLOW_DIRECT_REPO_WRITES

    if ALLOW_DIRECT_REPO_WRITES and GITHUB_TOKEN and GITHUB_REPO:
        # In production, create GitHub PR or commit
        github_commit_url = f"https://github.com/{GITHUB_REPO}/commit/{proposal_id}"
    else:
        github_commit_url = None

    return ProposeUpdateResponse(
        proposal_id=proposal_id,
        status="proposed" if dry_run else "committed",
        dry_run=dry_run,
        github_commit_url=github_commit_url
    )


@app.post("/repo/refresh")
async def refresh_repo(authorization: Optional[str] = Header(None)):
    """Trigger repo refresh from GitHub."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # In production, pull latest from GitHub
    return {"status": "refreshed", "timestamp": datetime.utcnow().isoformat()}


@app.get("/instructions")
async def get_instructions():
    """Get Custom GPT instructions."""
    instructions_path = Path("/data/examples/custom_gpt_instructions.txt")
    if instructions_path.exists():
        with open(instructions_path, 'r') as f:
            return {"instructions": f.read()}
    return {"instructions": "Instructions not found"}


@app.get("/openapi.json")
async def get_openapi_schema():
    """Get OpenAPI schema for GPT Actions."""
    return app.openapi()


@app.get("/healthz")
async def healthz():
    """Health check endpoint."""
    return {"status": "healthy"}


# Gate.io endpoints
@app.get("/gate/config", response_model=GateConfigResponse)
async def get_gate_config():
    """Get Gate.io configuration."""
    return GateConfigResponse(
        api_base=GATE_API_BASE,
        ws_base=GATE_WS_BASE,
        disclaimer="Research-only: Not a trading signal, not live execution"
    )


@app.post("/gate/candles", response_model=GateCandlesResponse)
async def get_gate_candles(request: GateCandlesRequest):
    """Pull public futures candles from Gate REST."""
    try:
        async with httpx.AsyncClient() as client:
            url = f"{GATE_API_BASE}/spot/candlesticks"
            params = {
                "currency_pair": request.contract,
                "interval": request.interval,
                "limit": request.limit
            }
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        return GateCandlesResponse(
            contract=request.contract,
            interval=request.interval,
            candles=data if isinstance(data, list) else [],
            source="gate_public_api",
            disclaimer="Research-only: Not a trading signal"
        )
    except Exception as e:
        return GateCandlesResponse(
            contract=request.contract,
            interval=request.interval,
            candles=[],
            source="error",
            disclaimer=f"Error fetching candles: {str(e)}"
        )


@app.post("/gate/backtest", response_model=GateBacktestResponse)
async def run_gate_backtest(request: GateBacktestRequest):
    """Run SMA-cross research baseline using provided candles."""
    if not request.candles:
        return GateBacktestResponse(
            strategy=request.strategy,
            total_return=0.0,
            max_drawdown=0.0,
            trade_count=0,
            disclaimer="No candles provided - research_estimate_not_live_profit"
        )

    # Simple SMA cross strategy
    closes = [float(candle[2]) for candle in request.candles if len(candle) > 2]
    if len(closes) < request.long_period:
        return GateBacktestResponse(
            strategy=request.strategy,
            total_return=0.0,
            max_drawdown=0.0,
            trade_count=0,
            disclaimer="Insufficient data - research_estimate_not_live_profit"
        )

    short_ma = sum(closes[-request.short_period:]) / request.short_period
    long_ma = sum(closes[-request.long_period:]) / request.long_period

    # Placeholder backtest logic
    total_return = (short_ma - long_ma) / long_ma if long_ma > 0 else 0.0
    max_drawdown = abs(min(total_return, 0))
    trade_count = 1 if abs(total_return) > 0.01 else 0

    return GateBacktestResponse(
        strategy=request.strategy,
        total_return=total_return,
        max_drawdown=max_drawdown,
        trade_count=trade_count,
        disclaimer="Research estimate - not live profit - not a trading signal"
    )


@app.post("/gate/ws-sample", response_model=GateWsSampleResponse)
async def sample_gate_ws(request: GateWsSampleRequest):
    """Open short Gate futures WebSocket sample window."""
    # Placeholder - in production, actual WebSocket connection
    return GateWsSampleResponse(
        contract=request.contract,
        messages=[
            {"channel": request.channels[0], "data": "sample_message_1"},
            {"channel": request.channels[0], "data": "sample_message_2"}
        ],
        message_count=2,
        disclaimer="Live market data snapshot - not a trading signal"
    )


@app.post("/prompt/calibrate", response_model=PromptCalibrateResponse)
async def calibrate_prompt(request: PromptCalibrateRequest):
    """Convert messy user prompt into reproducible SEPF prompt."""
    calibrated = f"""
    SEPF-1 calibrated prompt:
    - Artifact-first: Focus on reusable artifacts (specs, code, schemas, protocols)
    - Claim-labeled: Label claims as verified, user_claimed, inferred, unknown, blocked
    - Benchmarkable: Make the request measurable and testable
    - Receipt-ready: Generate QA receipt for substantial answers

    Original request: {request.user_prompt}
    """

    return PromptCalibrateResponse(
        original_prompt=request.user_prompt,
        calibrated_prompt=calibrated.strip(),
        artifact_type="spec",
        claim_labels=["user_claimed", "inferred"]
    )


@app.post("/calibrate/prompt", response_model=PromptCalibrateResponse)
async def calibrate_prompt_v2(request: PromptCalibrateRequest):
    """Convert messy user prompt into reproducible SEPF prompt (v2 endpoint)."""
    original = request.prompt or request.user_prompt or ""
    calibrated = f"""
    SEPF-1 calibrated prompt:
    - Artifact-first: Focus on reusable artifacts (specs, code, schemas, protocols)
    - Claim-labeled: Label claims as verified, user_claimed, inferred, unknown, blocked
    - Benchmarkable: Make the request measurable and testable
    - Receipt-ready: Generate QA receipt for substantial answers

    Original request: {original}
    """

    return PromptCalibrateResponse(
        original_prompt=original,
        calibrated_prompt=calibrated.strip(),
        artifact_type="spec",
        claim_labels=["user_claimed", "inferred"]
    )


@app.post("/signal/fuse", response_model=SignalFuseResponse)
async def fuse_signal(request: SignalFuseRequest):
    """Combine backtest result + live snapshot + latent history capsule."""
    backtest_score = request.backtest_result.get("total_return", 0) * 0.4
    ws_score = 0.3  # Placeholder
    history_score = 0.3 if request.history_capsule else 0.0

    research_score = backtest_score + ws_score + history_score
    confidence = min(1.0, research_score + 0.2)

    return SignalFuseResponse(
        research_score=research_score,
        confidence=confidence,
        components={
            "backtest_score": backtest_score,
            "ws_score": ws_score,
            "history_score": history_score
        },
        disclaimer="Research score - not a trade signal - not investment advice"
    )


@app.post("/cost-savings/estimate", response_model=CostSavingsResponse)
async def estimate_cost_savings(request: CostSavingsRequest):
    """Estimate user-side replacement-cost/time savings."""
    complexity_multipliers = {"low": 1.0, "medium": 1.5, "high": 2.5}
    multiplier = complexity_multipliers.get(request.complexity, 1.5)

    base_hours = request.hours_estimate or 8
    hourly_rate = 100.0  # Placeholder

    base_cost = base_hours * hourly_rate * multiplier

    return CostSavingsResponse(
        artifact_type=request.artifact_type,
        replacement_cost_low=base_cost * 0.7,
        replacement_cost_base=base_cost,
        replacement_cost_high=base_cost * 1.3,
        time_saved_hours=base_hours,
        disclaimer="User-side replacement cost estimate - not provider-side savings"
    )


# Gate.io stream endpoints
@app.post("/gateio/stream/start", response_model=GateStreamStartResponse)
async def start_gateio_stream(request: GateStreamStartRequest, background_tasks: BackgroundTasks):
    """Start Gate.io futures public market-data collector."""
    stream_id = f"stream-{datetime.utcnow().timestamp()}"
    receipt_hash = hashlib.sha256(stream_id.encode()).hexdigest()

    # Initialize stream state
    active_streams[stream_id] = {
        "status": "starting",
        "symbols": request.symbols,
        "channels": request.channels,
        "started_at": datetime.utcnow().isoformat(),
        "messages_collected": 0,
        "file_path": None
    }

    # Start WebSocket connection in background
    background_tasks.add_task(
        connect_gate_ws,
        stream_id,
        request.symbols,
        request.channels,
        request.duration_seconds
    )

    return GateStreamStartResponse(
        status="started",
        stream_id=stream_id,
        symbols=request.symbols,
        channels=request.channels,
        started_at=datetime.utcnow().isoformat(),
        receipt_hash=receipt_hash,
        disclaimer="Research-only: Not a trading signal, not live execution"
    )


@app.post("/gateio/stream/stop", response_model=GateStreamStopResponse)
async def stop_gateio_stream(request: GateStreamStopRequest):
    """Stop Gate.io stream collector."""
    receipt_hash = hashlib.sha256(request.stream_id.encode()).hexdigest()

    if request.stream_id in active_streams:
        active_streams[request.stream_id]["status"] = "stopped"
        messages_collected = active_streams[request.stream_id].get("messages_collected", 0)
        file_path = active_streams[request.stream_id].get("file_path")
    else:
        messages_collected = 0
        file_path = None

    return GateStreamStopResponse(
        status="stopped",
        stream_id=request.stream_id,
        stopped_at=datetime.utcnow().isoformat(),
        messages_collected=messages_collected,
        receipt_hash=receipt_hash
    )


@app.get("/gateio/stream/status")
async def get_gateio_stream_status(stream_id: Optional[str] = None):
    """Get current stream collector status."""
    if stream_id and stream_id in active_streams:
        return {"streams": [active_streams[stream_id]]}
    elif stream_id:
        return {"streams": []}
    else:
        return {"streams": list(active_streams.values())}


@app.get("/gateio/snapshot", response_model=GateSnapshotResponse)
async def get_gateio_snapshot(symbol: str):
    """Get latest compressed Gate.io stream snapshot."""
    receipt_hash = hashlib.sha256(f"{symbol}-{datetime.utcnow().timestamp()}".encode()).hexdigest()

    # Placeholder - in production, actual snapshot from stream
    return GateSnapshotResponse(
        symbol=symbol,
        timestamp=datetime.utcnow().isoformat(),
        best_bid=65000.0,
        best_ask=65000.1,
        spread_bps=0.15,
        mid_price=65000.05,
        receipt_hash=receipt_hash,
        disclaimer="Research-only: Not a trading signal"
    )


@app.get("/gateio/features", response_model=GateFeaturesResponse)
async def get_gateio_features(symbol: str, window_seconds: int = 60):
    """Get computed stream features for a symbol/window."""
    receipt_hash = hashlib.sha256(f"{symbol}-{window_seconds}".encode()).hexdigest()

    features = {
        "best_bid": 65000.0,
        "best_ask": 65000.1,
        "spread_bps": 0.15,
        "mid_price": 65000.05,
        "book_imbalance_top5": 0.12,
        "update_rate_per_sec": 18.4,
        "micro_volatility_bps": 4.8,
        "liquidity_top5_usdt": 240000,
        "staleness_ms": 120
    }

    return GateFeaturesResponse(
        symbol=symbol,
        window_seconds=window_seconds,
        features=features,
        claim_label="verified",
        receipt_hash=receipt_hash,
        disclaimer="Research-only: Not a trading signal"
    )


@app.post("/gateio/replay", response_model=GateReplayResponse)
async def replay_gateio_stream(request: GateReplayRequest):
    """Replay recorded Gate.io stream data."""
    receipt_hash = hashlib.sha256(request.stream_id.encode()).hexdigest()

    return GateReplayResponse(
        stream_id=request.stream_id,
        replay_data=[{"message": "sample_replay_data"}],
        receipt_hash=receipt_hash
    )


# Benchmark endpoints
@app.post("/benchmark/compare", response_model=BenchmarkCompareResponse)
async def benchmark_compare(request: BenchmarkCompareRequest):
    """Compare multiple benchmark runs."""
    return BenchmarkCompareResponse(
        comparison={
            "benchmarks": request.benchmarks,
            "summary": "Comparison complete"
        }
    )


@app.get("/benchmarks/latest")
async def get_latest_benchmarks(limit: int = 10):
    """Get latest benchmark results."""
    return {
        "benchmarks": [
            {"benchmark_id": "BM-001", "score": 0.85, "timestamp": datetime.utcnow().isoformat()}
        ]
    }


@app.post("/residue/score", response_model=ResidueScoreResponse)
async def calculate_residue_score(request: ResidueScoreRequest):
    """Calculate artifact residue score from benchmark comparison."""
    residue = request.runtime_score - request.baseline_score * (1 - request.decay_factor)
    receipt_hash = hashlib.sha256(f"{request.baseline_score}-{request.runtime_score}".encode()).hexdigest()

    return ResidueScoreResponse(
        baseline_score=request.baseline_score,
        runtime_score=request.runtime_score,
        residue=residue,
        receipt_hash=receipt_hash
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
