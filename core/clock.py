from pods.maintenance.engine import MaintenanceEngine

class TheClock:
    THRESHOLD = 4000  # Token limit before compression triggers
    
    @staticmethod
    def count_tokens(text: str):
        # Industrial estimation: ~4 chars per token for Gemini
        # This is fast, offline, and sufficient for maintenance triggers.
        return len(text) // 4

    @staticmethod
    async def maintenance_pulse(envelope):
        """
        The Automatic Check. Runs before every turn.
        If Truth is too heavy, it triggers a Compression Turn.
        """
        all_truth_text = str(envelope.knowledge_bricks)
        token_count = TheClock.count_tokens(all_truth_text)
        
        if token_count > TheClock.THRESHOLD:
            print(f"\n[CLOCK] Threshold Exceeded ({token_count} tokens). Running Automatic Compression...")
            
            brick_keys = list(envelope.knowledge_bricks.keys())
            if len(brick_keys) <= 3:
                return # Not enough bricks to compress yet
                
            # Keep last 3 bricks verbatim (Recency Bias)
            historical_keys = brick_keys[:-3]
            recent_keys = brick_keys[-3:]
            
            historical_data = {k: envelope.knowledge_bricks[k] for k in historical_keys}
            recent_data = {k: envelope.knowledge_bricks[k] for k in recent_keys}
            
            # 2. Compress the Past
            compressed_summary = await MaintenanceEngine.compress_truth(list(historical_data.values()))
            
            # 3. Rebuild the Truth Ledger
            new_ledger = {"FOUNDATIONAL_CONTEXT": compressed_summary}
            new_ledger.update(recent_data)
            
            envelope.knowledge_bricks = new_ledger
            print("[CLOCK] Truth Stabilized.")
