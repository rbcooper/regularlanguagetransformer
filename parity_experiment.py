"""
Experiment training a model on the parity task
"""

# %%

import torch as t


import transformer_lens
from transformer_lens import HookedTransformer
import numpy as np
import random
import plotly.express as px
import tqdm
import dfa_generator
from dfa_generator import DfaGenerator
# sklearn logistic regression
from sklearn.linear_model import LogisticRegression
from einops import reduce, repeat, rearrange


device = "cuda"
# %%
transformer_lens.HookedTransformerConfig

# reference_model = HookedTransformer.from_pretrained("gelu-4l", fold_ln=False, center_unembed=False, center_writing_weights=False)
# %%

cfg = transformer_lens.HookedTransformerConfig(**
{'act_fn': 'gelu',
 'attention_dir': 'causal',
 'attn_only': False,
 'attn_types': None,
 'checkpoint_index': None,
 'checkpoint_label_type': None,
 'checkpoint_value': None,
 'd_head': 32,
 'd_mlp': 512,
 'd_model': 128,
 'd_vocab': 256,
 'd_vocab_out': 256,
 'device': 'cuda',
 'eps': 1e-05,
 'final_rms': False,
 'from_checkpoint': False,
 'gated_mlp': False,
 'init_mode': 'gpt2',
 'init_weights': True,
 'initializer_range': 0.035355339059327376,
 'model_name': 'GELU_4L512W_C4_Code',
 'n_ctx': 32,
 'n_devices': 1,
 'n_heads': 4,
 'n_layers': 4,
 # 'n_params': 12582912,
 'normalization_type': 'LN',
 'original_architecture': 'neel',
 'parallel_attn_mlp': False,
 'positional_embedding_type': 'standard',
 'rotary_dim': None,
 'scale_attn_by_inverse_layer_idx': False,
 'seed': None,
#  'tokenizer_name': 'NeelNanda/gpt-neox-tokenizer-digits',
 'use_attn_result': False,
 'use_attn_scale': True,
 'use_hook_tokens': False,
 'use_local_attn': False,
 'use_split_qkv_input': False,
 'window_size': None}
)

# %%
cfg.n_params
# %%

model = HookedTransformer(cfg)

# %%

# 2 can only appear after an even number of 0s
gen = dfa_generator.DfaGenerator.from_regex('((B|C)*AB*A)*(B|C)*')
data_loader = gen.batches_and_states_gen(word_len=20, batch_size=32)
batch, states = data_loader.__next__()
batch.shape, states.shape
dfa_generator.display_fa(gen.dfa)
# %%


def loss_fn(logits, tokens, return_per_token=False):
    # logit shape: [batch, pos, vocab]
    # token shape: [batch, pos]
    # assert False
    logits = logits[:, :-1] # ignore last logit
    tokens = tokens[:, 1:] # ignore first token (bos token)
    log_probs = logits.log_softmax(-1)
    correct_log_probs = log_probs.gather(-1, tokens[..., None])[..., 0]
    loss = -correct_log_probs.mean() # mean over batch and pos
    return loss


# %%
# aa_train = make_aa_generator(seed=123)
# aa_test = make_aa_generator(seed=456)

def train_basic_model(model, gen:dfa_generator.DfaGenerator, batch_size=64, num_epochs=10_000, seed=123):
    print(f"Batch size: {batch_size}")
    lr = 1e-4
    betas = (0.9, 0.95)
    max_grad_norm = 1.0
    wd = 0.1
    optimizer = t.optim.AdamW(model.parameters(), lr=lr, betas=betas, weight_decay=wd)
    scheduler = t.optim.lr_scheduler.LambdaLR(optimizer, lambda i: min(i/100, 1.))
    data_loader = t.utils.data.DataLoader(gen.dataset(), batch_size=batch_size)
    print(data_loader)

    n_parameters = sum(p.numel() for p in model.parameters())
    parameter_size = n_parameters * model.parameters().__next__().element_size() / 1e6
    print(f"Model has {n_parameters} parameters = {parameter_size} MB")

    """## Model Training"""

    losses = []
    for epoch, (tokens, states) in tqdm.auto.tqdm(enumerate(data_loader), total=num_epochs):
        # print(tokens.device, states.device)
        tokens = tokens.cuda()
        logits = model(tokens)
        loss = loss_fn(logits, tokens)
        loss.backward()
        if max_grad_norm is not None:
            t.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
        optimizer.step()
        optimizer.zero_grad()
        scheduler.step()
        losses.append(loss.item())
        if epoch % 100 == 0:
            print(f'Epoch {epoch}: {loss.item()}')
        if epoch > num_epochs:
            break
    return losses

model = HookedTransformer(cfg)
# losses = train_basic_model(model, gen, batch_size=32, seed=123)
# %%
# fig = px.line(losses, labels={"x":"Epoch", "y":"Loss"})
# fig.show()


# Save model weights to file
model.load_state_dict(t.load('model_weights.pt'))
t.save(model.state_dict(), 'model_weights.pt')
# %%

def to_str(tokens):
    return "".join([chr(t) for t in tokens])

# prompt = t.zeros((1,20), dtype=t.int64)
# Generate 1000 completions and see how many of them have an even number of As
generated_tokens = model.generate(input=t.zeros((1000,1), dtype=t.int64),
                        eos_token_id=0, max_new_tokens=31,
                        do_sample=True, temperature=1)
even_As = [(sum(line == 65) % 2 == 0).item() for line in generated_tokens]
print(f"Fraction of completions with even number of As: {sum(even_As)/len(even_As)}")

generated_strings = [to_str(line).strip('\x00') for line in generated_tokens]
[x for x in zip(generated_strings, even_As)]

# Now make histogram of length, with color = whether it has even number of As
lengths = [len(s) for s in generated_strings]
fig = px.histogram(lengths, color=even_As, labels={"value":"Length", "color":"Even number of As"})
fig.show()

# %%


# %%


tokens, states = gen.batches_and_states_gen(batch_size=5000, word_len=model.cfg.n_ctx - 1).__next__()
print(tokens.device)
even_As_proportion = ((tokens == ord('A')).sum(axis=1) % 2 == 0).sum() / len(tokens)
print(f"Fraction of even As in true dataset: {even_As_proportion}")
# %%

# %%

# Training a linear probe to detect whether there are an even number of As so far


# First gather data: create a dataset, compute true states, and use model.run_with_cache to get hidden states
with t.inference_mode():
    model.eval()
    logits, cache = model.run_with_cache(tokens)
    print(f"logits is shape {logits.shape} with total {logits.numel()} elements")

# %%
# Now train a linear probe on states...
assert states[(states != 1) & (states != 2)].flatten().sum() == 0

# 0 = even, 1 = odd
states_transformed = states - 1
states_transformed = rearrange(states_transformed[:, 1:], 'b p -> (b p)').cpu().detach().numpy()

for layer in range(model.cfg.n_layers):
    for loc in ('mid', 'post'):
        resid = cache['resid_'+loc, layer]
        resid = rearrange(resid, 'b p d_model -> (b p) d_model')
        resid = resid.cpu().detach().numpy()
        # Use logistic regression to predict whether there are an even number of As
        lr = LogisticRegression(max_iter=1000)
        lr.fit(resid, states_transformed)

        score = lr.score(resid, states_transformed)
        print(f"Score for {layer} {loc}: {score}")
# %%
