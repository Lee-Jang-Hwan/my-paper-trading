-- ============================================================================
-- 001_initial_schema.sql
-- 한국 모의주식 거래 서비스 - 초기 데이터베이스 스키마
-- Supabase (PostgreSQL 15+) 호환
-- ============================================================================

-- ============================================================================
-- 1. 확장(Extension) 활성화
-- pgvector: AI 에이전트 메모리의 임베딩 벡터 유사도 검색에 사용
-- pg_partman: 시계열 데이터(주가, 분봉) 파티셔닝 관리에 사용
--   주의: pg_partman은 Supabase 대시보드에서 수동으로 활성화해야 할 수 있음
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector (임베딩 벡터 검색)
-- CREATE EXTENSION IF NOT EXISTS pg_partman; -- Supabase 대시보드에서 활성화 필요


-- ============================================================================
-- 2. user_profiles (사용자 프로필)
-- Clerk 인증 서비스와 연동되는 사용자 기본 정보
-- clerk_user_id를 통해 외부 인증 시스템과 매핑
-- ============================================================================
CREATE TABLE user_profiles (
    id             UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    clerk_user_id  TEXT        NOT NULL UNIQUE,
    nickname       TEXT,
    settings       JSONB       DEFAULT '{}',
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE  user_profiles IS '사용자 프로필 - Clerk 인증 연동';
COMMENT ON COLUMN user_profiles.clerk_user_id IS 'Clerk에서 발급한 사용자 고유 ID';
COMMENT ON COLUMN user_profiles.settings IS '사용자 개인 설정 (알림, 테마 등)';


-- ============================================================================
-- 3. accounts (가상 거래 계좌)
-- 사용자당 하나 이상의 모의투자 계좌를 보유할 수 있음
-- 초기 자본금 1,000만원 (10,000,000 KRW)
-- ============================================================================
CREATE TABLE accounts (
    id              UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
    clerk_user_id   TEXT        NOT NULL REFERENCES user_profiles(clerk_user_id),
    initial_capital BIGINT      NOT NULL DEFAULT 10000000,   -- 초기 자본금 (1,000만원)
    balance         BIGINT      NOT NULL DEFAULT 10000000,   -- 현재 현금 잔고
    total_asset     BIGINT      NOT NULL DEFAULT 10000000,   -- 총 자산 (현금 + 보유주식 평가액)
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE  accounts IS '모의투자 가상 계좌';
COMMENT ON COLUMN accounts.balance IS '현재 현금 잔고 (원 단위)';
COMMENT ON COLUMN accounts.total_asset IS '총 자산 = 현금 잔고 + 보유 주식 평가액';


-- ============================================================================
-- 4. stock_master (종목 마스터)
-- 한국 주식시장(KOSPI/KOSDAQ) 종목 기본 정보
-- 매일 장 마감 후 업데이트
-- ============================================================================
CREATE TABLE stock_master (
    stock_code   VARCHAR(20)  PRIMARY KEY,
    stock_name   VARCHAR(100) NOT NULL,
    market       VARCHAR(10)  NOT NULL,       -- 'KOSPI' 또는 'KOSDAQ'
    sector       VARCHAR(100),                -- 업종/섹터
    market_cap   BIGINT,                      -- 시가총액 (원)
    listing_date DATE,                        -- 상장일
    is_active    BOOLEAN      DEFAULT true,   -- 활성 종목 여부 (상장폐지 시 false)
    updated_at   TIMESTAMPTZ  DEFAULT NOW()
);

COMMENT ON TABLE  stock_master IS '종목 마스터 - KOSPI/KOSDAQ 종목 기본 정보';
COMMENT ON COLUMN stock_master.stock_code IS '종목 코드 (예: 005930 = 삼성전자)';
COMMENT ON COLUMN stock_master.market IS '시장 구분: KOSPI 또는 KOSDAQ';


-- ============================================================================
-- 5. holdings (보유 종목)
-- 사용자가 현재 보유 중인 주식 내역
-- 계좌-종목 조합은 유일해야 함 (UNIQUE 제약)
-- ============================================================================
CREATE TABLE holdings (
    id            UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    account_id    UUID         NOT NULL REFERENCES accounts(id),
    stock_code    VARCHAR(20)  NOT NULL REFERENCES stock_master(stock_code),
    stock_name    VARCHAR(100) NOT NULL,
    quantity      INTEGER      NOT NULL DEFAULT 0,   -- 보유 수량
    avg_price     INTEGER      NOT NULL DEFAULT 0,   -- 평균 매수 단가
    current_price INTEGER      NOT NULL DEFAULT 0,   -- 현재가
    created_at    TIMESTAMPTZ  DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  DEFAULT NOW(),

    UNIQUE(account_id, stock_code)
);

COMMENT ON TABLE  holdings IS '사용자 보유 종목 내역';
COMMENT ON COLUMN holdings.avg_price IS '평균 매수 단가 (원)';
COMMENT ON COLUMN holdings.current_price IS '마지막으로 갱신된 현재가';


-- ============================================================================
-- 6. orders (주문)
-- 매수/매도 주문 내역 (시장가, 지정가, 예약 주문)
-- 주문 상태: pending(대기) -> filled(체결) / partial(부분체결) / cancelled(취소) / rejected(거부)
-- ============================================================================
CREATE TABLE orders (
    id              UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    account_id      UUID         NOT NULL REFERENCES accounts(id),
    stock_code      VARCHAR(20)  NOT NULL,
    stock_name      VARCHAR(100),
    order_type      VARCHAR(10)  NOT NULL CHECK (order_type IN ('market', 'limit', 'scheduled')),
    side            VARCHAR(4)   NOT NULL CHECK (side IN ('buy', 'sell')),
    price           INTEGER,                         -- 지정가 (시장가 주문 시 NULL)
    quantity        INTEGER      NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'filled', 'partial', 'cancelled', 'rejected')),
    filled_quantity INTEGER      DEFAULT 0,          -- 체결된 수량
    filled_price    INTEGER,                         -- 체결 단가
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    filled_at       TIMESTAMPTZ,                     -- 체결 시각
    cancelled_at    TIMESTAMPTZ                      -- 취소 시각
);

COMMENT ON TABLE  orders IS '주문 내역 (매수/매도)';
COMMENT ON COLUMN orders.order_type IS '주문 유형: market(시장가), limit(지정가), scheduled(예약)';
COMMENT ON COLUMN orders.side IS '매매 구분: buy(매수), sell(매도)';
COMMENT ON COLUMN orders.status IS '주문 상태: pending, filled, partial, cancelled, rejected';


-- ============================================================================
-- 7. transactions (체결 내역)
-- 실제로 체결된 거래 기록
-- 수수료(fee)와 세금(tax) 포함
-- ============================================================================
CREATE TABLE transactions (
    id          UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    order_id    UUID         REFERENCES orders(id),
    account_id  UUID         NOT NULL REFERENCES accounts(id),
    stock_code  VARCHAR(20)  NOT NULL,
    side        VARCHAR(4)   NOT NULL,
    price       INTEGER      NOT NULL,       -- 체결 단가
    quantity    INTEGER      NOT NULL,       -- 체결 수량
    fee         INTEGER      DEFAULT 0,      -- 거래 수수료
    tax         INTEGER      DEFAULT 0,      -- 거래세 (매도 시)
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

COMMENT ON TABLE  transactions IS '체결된 거래 기록';
COMMENT ON COLUMN transactions.fee IS '거래 수수료 (원)';
COMMENT ON COLUMN transactions.tax IS '거래세 - 매도 시 부과 (원)';


-- ============================================================================
-- 8. stock_prices (일봉 OHLCV)
-- 일별 시가/고가/저가/종가/거래량
-- 월별 파티셔닝으로 대량 시계열 데이터 효율적 관리
-- ============================================================================
CREATE TABLE stock_prices (
    time       TIMESTAMPTZ  NOT NULL,
    stock_code VARCHAR(20)  NOT NULL,
    open       INTEGER,           -- 시가
    high       INTEGER,           -- 고가
    low        INTEGER,           -- 저가
    close      INTEGER,           -- 종가
    volume     BIGINT,            -- 거래량

    PRIMARY KEY (time, stock_code)
) PARTITION BY RANGE (time);

COMMENT ON TABLE  stock_prices IS '일봉 데이터 (OHLCV) - 월별 파티셔닝';
COMMENT ON COLUMN stock_prices.time IS '거래일 (일봉 기준)';


-- ============================================================================
-- 9. stock_minutes (분봉 OHLCV)
-- 분 단위 시가/고가/저가/종가/거래량
-- 월별 파티셔닝으로 대량 시계열 데이터 효율적 관리
-- ============================================================================
CREATE TABLE stock_minutes (
    time       TIMESTAMPTZ  NOT NULL,
    stock_code VARCHAR(20)  NOT NULL,
    open       INTEGER,           -- 시가
    high       INTEGER,           -- 고가
    low        INTEGER,           -- 저가
    close      INTEGER,           -- 종가
    volume     BIGINT,            -- 거래량

    PRIMARY KEY (time, stock_code)
) PARTITION BY RANGE (time);

COMMENT ON TABLE  stock_minutes IS '분봉 데이터 (OHLCV) - 월별 파티셔닝';
COMMENT ON COLUMN stock_minutes.time IS '분봉 타임스탬프';


-- ============================================================================
-- 10. news (뉴스)
-- 크롤링된 금융/주식 관련 뉴스
-- 감성 분석 점수와 관련 종목 태깅 포함
-- ============================================================================
CREATE TABLE news (
    id              UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    title           TEXT         NOT NULL,
    content         TEXT,
    source          VARCHAR(50),              -- 뉴스 출처 (예: 연합뉴스, 한경)
    url             TEXT,
    sentiment_score REAL,                     -- 감성 분석 점수 (-1.0 ~ 1.0)
    related_stocks  TEXT[],                   -- 관련 종목 코드 배열
    published_at    TIMESTAMPTZ,              -- 기사 발행 시각
    crawled_at      TIMESTAMPTZ  DEFAULT NOW() -- 크롤링 시각
);

COMMENT ON TABLE  news IS '금융 뉴스 - 크롤링 및 감성 분석';
COMMENT ON COLUMN news.sentiment_score IS '감성 분석 점수: -1.0(매우 부정) ~ 1.0(매우 긍정)';
COMMENT ON COLUMN news.related_stocks IS '관련 종목 코드 배열 (예: {005930,000660})';


-- ============================================================================
-- 11. agent_memories (AI 에이전트 메모리 스트림)
-- Generative Agents 아키텍처 기반 에이전트 기억 저장소
-- 관찰(observation), 대화(conversation), 성찰(reflection), 계획(plan) 유형
-- pgvector 임베딩을 통한 유사도 기반 기억 검색 지원
-- ============================================================================
CREATE TABLE agent_memories (
    id                  UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    agent_type          VARCHAR(20)  NOT NULL,        -- trend, advisor, news, portfolio
    memory_type         VARCHAR(20)  NOT NULL,        -- observation, conversation, reflection, plan
    content             TEXT         NOT NULL,
    importance_score    REAL         NOT NULL DEFAULT 5.0,  -- 중요도 점수 (1~10)
    embedding           VECTOR(768),                  -- 텍스트 임베딩 벡터 (768차원)
    related_stock_codes TEXT[],                        -- 관련 종목 코드 배열
    created_at          TIMESTAMPTZ  DEFAULT NOW(),
    last_accessed_at    TIMESTAMPTZ  DEFAULT NOW(),   -- 마지막 접근 시각 (recency 계산용)
    archived_at         TIMESTAMPTZ                   -- 아카이브 시각 (NULL이면 활성 상태)
);

COMMENT ON TABLE  agent_memories IS 'Generative Agents 메모리 스트림';
COMMENT ON COLUMN agent_memories.agent_type IS '에이전트 유형: trend(추세), advisor(조언), news(뉴스), portfolio(포트폴리오)';
COMMENT ON COLUMN agent_memories.memory_type IS '기억 유형: observation(관찰), conversation(대화), reflection(성찰), plan(계획)';
COMMENT ON COLUMN agent_memories.importance_score IS '중요도 점수 (1~10, 기본값 5)';
COMMENT ON COLUMN agent_memories.embedding IS '텍스트 임베딩 벡터 - 유사도 검색에 사용';


-- ============================================================================
-- 12. agent_conversations (에이전트 간 대화)
-- 에이전트 간의 대화 기록
-- 어떤 에이전트가 어떤 에이전트에게, 어떤 주제로 대화했는지 저장
-- ============================================================================
CREATE TABLE agent_conversations (
    id                UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    initiator_agent   VARCHAR(20)  NOT NULL,         -- 대화 시작 에이전트
    target_agent      VARCHAR(20)  NOT NULL,         -- 대화 대상 에이전트
    topic             TEXT         NOT NULL,          -- 대화 주제
    conversation_json JSONB        NOT NULL,          -- 대화 내용 (JSON 형식)
    conclusion        TEXT,                           -- 대화 결론/요약
    trigger_event     TEXT,                           -- 대화를 촉발한 이벤트
    created_at        TIMESTAMPTZ  DEFAULT NOW()
);

COMMENT ON TABLE  agent_conversations IS '에이전트 간 대화 기록';
COMMENT ON COLUMN agent_conversations.conversation_json IS '대화 내용: [{role, content, timestamp}, ...]';


-- ============================================================================
-- 13. agent_plans (에이전트 일일 계획)
-- 각 에이전트의 일일 행동 계획
-- Generative Agents의 Planning 모듈에 해당
-- ============================================================================
CREATE TABLE agent_plans (
    id          UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    agent_type  VARCHAR(20)  NOT NULL,
    plan_date   DATE         NOT NULL,               -- 계획 날짜
    plan_json   JSONB        NOT NULL,               -- 계획 내용 (시간별 행동 계획)
    status      VARCHAR(20)  DEFAULT 'active',       -- active, completed, cancelled
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

COMMENT ON TABLE  agent_plans IS '에이전트 일일 행동 계획';
COMMENT ON COLUMN agent_plans.plan_json IS '시간별 행동 계획: [{time, action, duration}, ...]';


-- ============================================================================
-- 14. agent_reflections (에이전트 성찰)
-- 에이전트가 축적된 기억을 바탕으로 수행한 성찰 기록
-- 중요도 합산이 임계값을 넘으면 자동으로 성찰 수행
-- ============================================================================
CREATE TABLE agent_reflections (
    id               UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    agent_type       VARCHAR(20)  NOT NULL,
    trigger_memories UUID[],                          -- 성찰을 촉발한 기억 ID 배열
    questions_json   JSONB,                           -- 성찰 질문들
    insights_json    JSONB,                           -- 도출된 인사이트들
    created_at       TIMESTAMPTZ  DEFAULT NOW()
);

COMMENT ON TABLE  agent_reflections IS '에이전트 성찰 기록';
COMMENT ON COLUMN agent_reflections.trigger_memories IS '성찰을 촉발한 기억 ID 배열';
COMMENT ON COLUMN agent_reflections.insights_json IS '성찰을 통해 도출된 인사이트: [{insight, evidence}, ...]';


-- ============================================================================
-- 15. agent_state_log (에이전트 상태 로그)
-- 에이전트의 현재 상태/위치/행동을 시간순으로 기록
-- Generative Agents의 sandbox world 위치 추적에 해당
-- ============================================================================
CREATE TABLE agent_state_log (
    id           UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    agent_type   VARCHAR(20)  NOT NULL,
    location     VARCHAR(50),                         -- 에이전트 현재 위치 (가상 공간)
    action       TEXT,                                -- 현재 수행 중인 행동
    status_emoji VARCHAR(10),                         -- 상태 이모지 (UI 표시용)
    status_text  TEXT,                                -- 상태 텍스트 (UI 표시용)
    target_agent VARCHAR(20),                         -- 상호작용 대상 에이전트
    created_at   TIMESTAMPTZ  DEFAULT NOW()
);

COMMENT ON TABLE  agent_state_log IS '에이전트 상태/위치/행동 로그';
COMMENT ON COLUMN agent_state_log.location IS '에이전트 가상 위치 (예: 차트분석실, 뉴스룸)';


-- ============================================================================
-- 16. ai_reports (AI 분석 리포트)
-- 각 에이전트가 생성한 분석 리포트
-- 종목 분석, 시장 전망, 포트폴리오 제안 등
-- ============================================================================
CREATE TABLE ai_reports (
    id          UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    agent_type  VARCHAR(20)  NOT NULL,
    stock_code  VARCHAR(20),                          -- 관련 종목 (시장 전체 리포트면 NULL)
    report_type VARCHAR(50)  NOT NULL,                -- 리포트 유형 (daily, weekly, alert 등)
    content     JSONB        NOT NULL,                -- 리포트 내용
    confidence  REAL,                                 -- 신뢰도 점수 (0.0 ~ 1.0)
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);

COMMENT ON TABLE  ai_reports IS 'AI 에이전트 분석 리포트';
COMMENT ON COLUMN ai_reports.report_type IS '리포트 유형: daily(일일), weekly(주간), alert(긴급) 등';
COMMENT ON COLUMN ai_reports.confidence IS '분석 신뢰도: 0.0(낮음) ~ 1.0(높음)';


-- ============================================================================
-- 17. predictions (예측)
-- ML/AI 모델의 주가 예측 결과와 실제 결과 비교
-- 모델 성능 추적 및 백테스팅에 활용
-- ============================================================================
CREATE TABLE predictions (
    id            UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    model_type    VARCHAR(50)  NOT NULL,              -- 모델 유형 (lstm, transformer 등)
    stock_code    VARCHAR(20)  NOT NULL,
    prediction    JSONB        NOT NULL,              -- 예측 결과 (방향, 목표가 등)
    confidence    REAL,                               -- 예측 신뢰도
    actual_result JSONB,                              -- 실제 결과 (사후 기록)
    created_at    TIMESTAMPTZ  DEFAULT NOW()
);

COMMENT ON TABLE  predictions IS 'AI 모델 주가 예측 결과';
COMMENT ON COLUMN predictions.prediction IS '예측 내용: {direction, target_price, horizon, ...}';
COMMENT ON COLUMN predictions.actual_result IS '실제 결과 (사후 기록): {actual_price, accuracy, ...}';


-- ============================================================================
-- 인덱스 생성
-- 쿼리 성능 최적화를 위한 인덱스
-- ============================================================================

-- accounts: 사용자별 계좌 조회 최적화
CREATE INDEX idx_accounts_clerk_user_id ON accounts(clerk_user_id);

-- holdings: 계좌별/종목별 보유 내역 조회
CREATE INDEX idx_holdings_account_id ON holdings(account_id);
CREATE INDEX idx_holdings_stock_code ON holdings(stock_code);

-- orders: 계좌별 주문 조회, 상태별 필터링, 시간순 정렬
CREATE INDEX idx_orders_account_id ON orders(account_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at);

-- transactions: 계좌별 체결 내역 조회, 시간순 정렬
CREATE INDEX idx_transactions_account_id ON transactions(account_id);
CREATE INDEX idx_transactions_created_at ON transactions(created_at);

-- stock_prices: 종목별 시간 범위 조회 최적화
-- 참고: 파티션 테이블에서는 각 파티션에 자동 생성됨
CREATE INDEX idx_stock_prices_stock_code_time ON stock_prices(stock_code, time);

-- stock_minutes: 종목별 시간 범위 조회 최적화
CREATE INDEX idx_stock_minutes_stock_code_time ON stock_minutes(stock_code, time);

-- agent_memories: 에이전트/기억 유형별 조회, 시간순 정렬, 아카이브 필터링
CREATE INDEX idx_agent_memories_agent_type ON agent_memories(agent_type);
CREATE INDEX idx_agent_memories_memory_type ON agent_memories(memory_type);
CREATE INDEX idx_agent_memories_created_at ON agent_memories(created_at);
CREATE INDEX idx_agent_memories_archived_at ON agent_memories(archived_at);

-- agent_memories: 임베딩 벡터 유사도 검색 (IVFFlat 인덱스)
-- 참고: 데이터가 충분히 쌓인 후(최소 수천 건) 생성하는 것이 효과적
-- lists = 100은 약 10,000~100,000건의 데이터에 적합
CREATE INDEX idx_agent_memories_embedding ON agent_memories
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- news: 발행 시각별 정렬, 관련 종목 검색 (GIN 인덱스)
CREATE INDEX idx_news_published_at ON news(published_at);
CREATE INDEX idx_news_related_stocks ON news USING GIN (related_stocks);


-- ============================================================================
-- 파티션 생성 (stock_prices - 일봉)
-- 2026년 1월 ~ 12월 월별 파티션
-- 데이터가 해당 월의 파티션에 자동으로 라우팅됨
-- ============================================================================

CREATE TABLE stock_prices_2026_01 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE stock_prices_2026_02 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE stock_prices_2026_03 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE stock_prices_2026_04 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE stock_prices_2026_05 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE stock_prices_2026_06 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE stock_prices_2026_07 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE stock_prices_2026_08 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE stock_prices_2026_09 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE stock_prices_2026_10 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE stock_prices_2026_11 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE stock_prices_2026_12 PARTITION OF stock_prices
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');


-- ============================================================================
-- 파티션 생성 (stock_minutes - 분봉)
-- 2026년 1월 ~ 12월 월별 파티션
-- ============================================================================

CREATE TABLE stock_minutes_2026_01 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE stock_minutes_2026_02 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE stock_minutes_2026_03 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE stock_minutes_2026_04 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE stock_minutes_2026_05 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE stock_minutes_2026_06 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE stock_minutes_2026_07 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE stock_minutes_2026_08 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE stock_minutes_2026_09 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE stock_minutes_2026_10 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE stock_minutes_2026_11 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE stock_minutes_2026_12 PARTITION OF stock_minutes
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');


-- ============================================================================
-- Row Level Security (RLS) 정책
-- Supabase 인증 기반 행 수준 보안
-- auth.jwt()->>'sub' : Clerk JWT의 subject 클레임 (사용자 ID)
-- ============================================================================

-- ---------------------------------------------------------------------------
-- user_profiles RLS
-- 사용자는 자신의 프로필만 조회/수정 가능
-- ---------------------------------------------------------------------------
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_profiles_select_own"
    ON user_profiles FOR SELECT
    USING (clerk_user_id = auth.jwt()->>'sub');

CREATE POLICY "user_profiles_insert_own"
    ON user_profiles FOR INSERT
    WITH CHECK (clerk_user_id = auth.jwt()->>'sub');

CREATE POLICY "user_profiles_update_own"
    ON user_profiles FOR UPDATE
    USING (clerk_user_id = auth.jwt()->>'sub')
    WITH CHECK (clerk_user_id = auth.jwt()->>'sub');

CREATE POLICY "user_profiles_delete_own"
    ON user_profiles FOR DELETE
    USING (clerk_user_id = auth.jwt()->>'sub');


-- ---------------------------------------------------------------------------
-- accounts RLS
-- 사용자는 자신의 계좌만 조회/수정 가능
-- ---------------------------------------------------------------------------
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "accounts_select_own"
    ON accounts FOR SELECT
    USING (clerk_user_id = auth.jwt()->>'sub');

CREATE POLICY "accounts_insert_own"
    ON accounts FOR INSERT
    WITH CHECK (clerk_user_id = auth.jwt()->>'sub');

CREATE POLICY "accounts_update_own"
    ON accounts FOR UPDATE
    USING (clerk_user_id = auth.jwt()->>'sub')
    WITH CHECK (clerk_user_id = auth.jwt()->>'sub');

CREATE POLICY "accounts_delete_own"
    ON accounts FOR DELETE
    USING (clerk_user_id = auth.jwt()->>'sub');


-- ---------------------------------------------------------------------------
-- holdings RLS
-- 사용자는 자신의 계좌에 연결된 보유 종목만 조회/수정 가능
-- accounts 테이블과 JOIN하여 소유권 확인
-- ---------------------------------------------------------------------------
ALTER TABLE holdings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "holdings_select_own"
    ON holdings FOR SELECT
    USING (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );

CREATE POLICY "holdings_insert_own"
    ON holdings FOR INSERT
    WITH CHECK (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );

CREATE POLICY "holdings_update_own"
    ON holdings FOR UPDATE
    USING (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    )
    WITH CHECK (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );

CREATE POLICY "holdings_delete_own"
    ON holdings FOR DELETE
    USING (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );


-- ---------------------------------------------------------------------------
-- orders RLS
-- 사용자는 자신의 계좌에 연결된 주문만 조회/수정 가능
-- ---------------------------------------------------------------------------
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY "orders_select_own"
    ON orders FOR SELECT
    USING (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );

CREATE POLICY "orders_insert_own"
    ON orders FOR INSERT
    WITH CHECK (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );

CREATE POLICY "orders_update_own"
    ON orders FOR UPDATE
    USING (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    )
    WITH CHECK (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );

CREATE POLICY "orders_delete_own"
    ON orders FOR DELETE
    USING (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );


-- ---------------------------------------------------------------------------
-- transactions RLS
-- 사용자는 자신의 계좌에 연결된 체결 내역만 조회 가능
-- 체결 기록은 시스템에서만 생성하므로 INSERT/UPDATE/DELETE는 service_role만 가능
-- ---------------------------------------------------------------------------
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "transactions_select_own"
    ON transactions FOR SELECT
    USING (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );

CREATE POLICY "transactions_insert_own"
    ON transactions FOR INSERT
    WITH CHECK (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );

CREATE POLICY "transactions_update_own"
    ON transactions FOR UPDATE
    USING (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    )
    WITH CHECK (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );

CREATE POLICY "transactions_delete_own"
    ON transactions FOR DELETE
    USING (
        account_id IN (
            SELECT id FROM accounts WHERE clerk_user_id = auth.jwt()->>'sub'
        )
    );


-- ---------------------------------------------------------------------------
-- 공개 읽기 테이블 (RLS 불필요)
-- stock_master, stock_prices, stock_minutes, news, predictions,
-- ai_reports, agent_* 테이블은 공개 읽기 허용
-- 쓰기는 service_role 키를 사용하는 백엔드 서비스만 가능
-- ---------------------------------------------------------------------------
-- 이 테이블들은 RLS를 활성화하지 않으므로 anon/authenticated 역할로 읽기 가능
-- 쓰기 작업은 백엔드에서 service_role 키로 수행


-- ============================================================================
-- 스키마 생성 완료
-- ============================================================================
-- 총 17개 테이블:
--   - 사용자/거래: user_profiles, accounts, holdings, orders, transactions
--   - 시장 데이터: stock_master, stock_prices(파티션), stock_minutes(파티션), news
--   - AI 에이전트: agent_memories, agent_conversations, agent_plans,
--                  agent_reflections, agent_state_log
--   - AI 분석: ai_reports, predictions
--
-- RLS 적용: user_profiles, accounts, holdings, orders, transactions
-- 파티셔닝: stock_prices (2026-01 ~ 2026-12), stock_minutes (2026-01 ~ 2026-12)
-- 벡터 검색: agent_memories.embedding (IVFFlat, lists=100)
-- ============================================================================
