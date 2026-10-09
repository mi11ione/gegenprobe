// llscore: forced-choice log-probabilities from a GGUF via libllama (Metal), for the 261bis GGUF parity run.
// Build: c++ -std=c++17 -O2 llscore.cpp -I$(brew --prefix llama.cpp)/include -L$(brew --prefix llama.cpp)/lib -lllama -o llscore
// Modes:
//   llscore <model.gguf> score   stdin lines: "<prompt ids> ; <cand1 ids> ; <cand2 ids> ..." (space-separated token ids)
//                                stdout line per input: "<sum lp cand1> <sum lp cand2> ... | <per-token lps cand1 , ...>"
//                                The prompt is decoded once; each candidate is scored by teacher forcing on top of it and
//                                then trimmed from the KV cache (same arithmetic as stage9.py score_conts / forced_choice).
//   llscore <model.gguf> tok     stdin: records separated by 0x1e; stdout line per record: token ids from llama.cpp's own
//                                tokenizer (add_special=false, parse_special=true), to compare with the HF/MLX tokenizer.
//   llscore <model.gguf> meta    print a few GGUF metadata keys and the embedded chat template.
#include "llama.h"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

static double g_extra = 0; // log of the probability mass on rows >= nv (rows the HF/MLX head does not have)
static std::vector<double> logsoftmax_at(const float *lg, int nv, const std::vector<int> &want, int nfull = 0) {
    if (nfull > nv) {  // diagnostic: log P(rows >= nv) under the full-vocab softmax
        double mf = -1e300; for (int i = 0; i < nfull; i++) mf = std::max(mf, (double)lg[i]);
        double sa = 0, se = 0; for (int i = 0; i < nfull; i++) { double e = std::exp((double)lg[i] - mf); sa += e; if (i >= nv) se += e; }
        g_extra = se > 0 ? std::log(se / sa) : -1e300;
    }
    double m = -1e300;
    for (int i = 0; i < nv; i++) m = std::max(m, (double)lg[i]);
    double s = 0;
    for (int i = 0; i < nv; i++) s += std::exp((double)lg[i] - m);
    double lse = m + std::log(s);
    std::vector<double> out;
    for (int t : want) out.push_back((double)lg[t] - lse);
    return out;
}

static void fill(llama_batch &b, const std::vector<int> &ids, int pos0, int out_from) {
    b.n_tokens = (int)ids.size();
    for (size_t i = 0; i < ids.size(); i++) {
        b.token[i] = ids[i]; b.pos[i] = pos0 + (int)i; b.n_seq_id[i] = 1; b.seq_id[i][0] = 0;
        b.logits[i] = ((int)i >= out_from) ? 1 : 0;
    }
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: llscore model.gguf score|tok|meta\n"); return 2; }
    std::string mode = argv[2];
    llama_backend_init();
    auto mp = llama_model_default_params();
    mp.n_gpu_layers = 999;
    if (mode != "score") mp.vocab_only = true;
    llama_model *model = llama_model_load_from_file(argv[1], mp);
    if (!model) { fprintf(stderr, "load failed\n"); return 1; }
    const llama_vocab *vocab = llama_model_get_vocab(model);
    const int nv_full = llama_vocab_n_tokens(vocab);
    // normalise over the first LLSCORE_NV rows (default: all) so the softmax matches a head with that many rows
    const int nv = getenv("LLSCORE_NV") ? std::min(nv_full, atoi(getenv("LLSCORE_NV"))) : nv_full;

    if (mode == "meta") {
        const char *keys[] = {"general.architecture", "general.name", "general.file_type", "general.quantization_version",
                              "tokenizer.ggml.model", "tokenizer.ggml.pre", "tokenizer.ggml.bos_token_id", "tokenizer.ggml.add_bos_token"};
        char buf[512];
        for (auto k : keys) { int r = llama_model_meta_val_str(model, k, buf, sizeof buf); printf("%s = %s\n", k, r >= 0 ? buf : "(absent)"); }
        printf("n_vocab = %d (normalised over %d)\n", nv_full, nv);
        const char *tmpl = llama_model_chat_template(model, nullptr);
        printf("CHAT_TEMPLATE_BEGIN\n%s\nCHAT_TEMPLATE_END\n", tmpl ? tmpl : "(none)");
        return 0;
    }
    if (mode == "tok") {
        std::string all((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
        size_t p = 0;
        while (p <= all.size()) {
            size_t q = all.find('\x1e', p); if (q == std::string::npos) q = all.size();
            std::string rec = all.substr(p, q - p);
            if (!rec.empty() || q < all.size()) {
                int n = -llama_tokenize(vocab, rec.data(), (int)rec.size(), nullptr, 0, false, true);
                std::vector<llama_token> ids(std::max(n, 1));
                int r = llama_tokenize(vocab, rec.data(), (int)rec.size(), ids.data(), (int)ids.size(), false, true);
                for (int i = 0; i < r; i++) printf(i ? " %d" : "%d", ids[i]);
                printf("\n");
            }
            if (q >= all.size()) break;
            p = q + 1;
        }
        return 0;
    }

    auto cp = llama_context_default_params();
    cp.n_ctx = 4096; cp.n_batch = 2048; cp.n_ubatch = 512; cp.n_seq_max = 1; cp.no_perf = true;
    llama_context *ctx = llama_init_from_model(model, cp);
    if (!ctx) { fprintf(stderr, "ctx failed\n"); return 1; }
    llama_memory_t mem = llama_get_memory(ctx);
    llama_batch b = llama_batch_init(2048, 0, 1);
    fprintf(stderr, "READY n_vocab=%d norm=%d\n", nv_full, nv);

    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        std::vector<std::vector<int>> groups(1);
        std::stringstream ss(line); std::string tkn;
        while (ss >> tkn) { if (tkn == ";") groups.emplace_back(); else groups.back().push_back(std::stoi(tkn)); }
        std::vector<int> &prompt = groups[0];
        const int n = (int)prompt.size();
        llama_memory_clear(mem, true);
        std::vector<double> first;
        std::vector<int> firsts;
        for (size_t c = 1; c < groups.size(); c++) firsts.push_back(groups[c][0]);
        for (int s = 0; s < n; s += 2048) {
            std::vector<int> chunk(prompt.begin() + s, prompt.begin() + std::min(n, s + 2048));
            fill(b, chunk, s, (s + (int)chunk.size() == n) ? (int)chunk.size() - 1 : (int)chunk.size());
            if (llama_decode(ctx, b) != 0) { fprintf(stderr, "decode failed\n"); return 1; }
        }
        first = logsoftmax_at(llama_get_logits_ith(ctx, -1), nv, firsts, nv_full);
        std::ostringstream sums, per; sums.precision(10); per.precision(8);
        for (size_t c = 1; c < groups.size(); c++) {
            std::vector<int> &ids = groups[c];
            double tot = first[c - 1];
            per << (c > 1 ? " , " : "") << first[c - 1];
            if (ids.size() > 1) {
                std::vector<int> ext(ids.begin(), ids.end() - 1);
                fill(b, ext, n, 0);
                if (llama_decode(ctx, b) != 0) { fprintf(stderr, "decode failed\n"); return 1; }
                for (size_t j = 0; j + 1 < ids.size(); j++) {
                    double lp = logsoftmax_at(llama_get_logits_ith(ctx, (int)j), nv, {ids[j + 1]})[0];
                    tot += lp; per << " " << lp;
                }
                llama_memory_seq_rm(mem, 0, n, -1);
            }
            sums << (c > 1 ? " " : "") << tot;
        }
        printf("%s | %s | extra %.4f\n", sums.str().c_str(), per.str().c_str(), g_extra);
        fflush(stdout);
    }
    llama_batch_free(b);
    llama_free(ctx);
    llama_model_free(model);
    return 0;
}
