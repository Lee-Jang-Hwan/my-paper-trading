-- 002: agent_conversations 테이블에 conversation_id 컬럼 추가
-- 실시간 토론 추적을 위한 고유 식별자

ALTER TABLE agent_conversations
ADD COLUMN IF NOT EXISTS conversation_id UUID DEFAULT gen_random_uuid();

CREATE INDEX IF NOT EXISTS idx_agent_conversations_conversation_id
ON agent_conversations(conversation_id);
