"""Optional faster decode for Unlimited-OCR-2 on CPU (OCR_FAST_DECODE, docs/ocr.md).

On CPU a decode step is bound by Python/op-dispatch overhead, not by FLOPs. Two opt-in patches of
the model's remote code (class/module level, switched by LEVEL at call time):
- level >= 1, single-token MoE: the generic `moe_infer` (argsort, scatter, numpy round trip, loop
  over 64 experts) is replaced for one token by direct calls of its 6 routed experts. Same math and
  summation order, so the output is unchanged.
- level >= 2, dense decode attention: the DASH block router (index keys, block scores, entmax
  top-k, bias-aware sparse attend) is replaced by plain softmax attention over the whole KV cache.
  This is an approximation of what the model was deployed with; judged by scripts/ocr_probe.py.
Prefill (the image + prompt) is never changed.
"""

import importlib

LEVEL = {"value": 0}
_patched: set[str] = set()


def install(model) -> None:
    """Patch the model's classes/modules once per process; behaviour follows LEVEL."""
    import torch
    import torch.nn.functional as F

    pkg = type(model).__module__.rsplit(".", 1)[0]
    if pkg in _patched:
        return
    base = importlib.import_module(f"{pkg}._sparse_base_impl")
    dash = importlib.import_module(f"{pkg}.modeling_deepseekv2")

    moe_cls = base.DeepseekV2MoE
    orig_moe_infer = moe_cls.moe_infer

    @torch.no_grad()
    def moe_infer(self, x, topk_ids, topk_weight):
        if LEVEL["value"] < 1 or x.shape[0] != 1 or self.ep_size != 1:
            return orig_moe_infer(self, x, topk_ids, topk_weight)
        outs = []
        for e in topk_ids[0].tolist():
            ex = self.experts[e]
            outs.append(ex.down_proj(F.silu(ex.gate_proj(x)) * ex.up_proj(x)))
        y = torch.cat(outs, dim=0).type(topk_weight.dtype) * topk_weight[0].unsqueeze(-1)
        return y.sum(dim=0, keepdim=True).type(x.dtype)

    moe_cls.moe_infer = moe_infer

    orig_decode = dash._dash_decode_forward

    @torch.no_grad()
    def decode_forward(self, hidden_states, position_ids, past_kv):
        if LEVEL["value"] < 2:
            return orig_decode(self, hidden_states, position_ids, past_kv)
        nh, nkv = self.config.num_attention_heads, self.config.num_key_value_heads
        hd = self.head_dim
        bsz, q_len, _ = hidden_states.size()
        if position_ids is None:
            past = past_kv.get_seq_length(self.layer_idx)
            position_ids = torch.arange(past, past + q_len)[None].expand(bsz, -1)
        q = self.q_proj(hidden_states).view(bsz, q_len, nh, hd).transpose(1, 2)
        k = self.k_proj(hidden_states).view(bsz, q_len, nkv, hd).transpose(1, 2)
        v = self.v_proj(hidden_states).view(bsz, q_len, nkv, hd).transpose(1, 2)
        coords = None  # same rope as the original (advances its page/token state machine once)
        if self.main_rope_mode == "page2d" and self.rotary_emb_2d_main is not None:
            coords = self._main_rope_coords(q_len, past_kv)
        if coords is not None:
            cos, sin = self.rotary_emb_2d_main(v, coords[0], coords[1])
        else:
            cos, sin = self.rotary_emb(v, position_ids)
        q, k = dash._llama_apply_rotary_pos_emb(q, k, cos, sin)
        k_all, v_all = past_kv.update(k, v, self.layer_idx)
        if nkv != nh:
            k_all = dash._llama_repeat_kv(k_all, nh // nkv)
            v_all = dash._llama_repeat_kv(v_all, nh // nkv)
        out = F.scaled_dot_product_attention(
            q.float(), k_all.float(), v_all.float(), scale=self.dash_router._scale
        )
        out = out.to(hidden_states.dtype).transpose(1, 2).contiguous().reshape(bsz, q_len, -1)
        return self.o_proj(out), None, past_kv, None

    dash._dash_decode_forward = decode_forward
    _patched.add(pkg)
