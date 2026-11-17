#include <algorithm>
#include <cstdint>
#include <string>
#include <string_view>

namespace {

inline void append_ascii_lower(const uint8_t* ptr, int32_t start, int32_t end, std::string& out) {
    out.clear();
    out.reserve(static_cast<size_t>(end - start));
    for (int32_t i = start; i < end; ++i) {
        const uint8_t ch = ptr[i];
        if (ch >= 'A' && ch <= 'Z') {
            out.push_back(static_cast<char>(ch + ('a' - 'A')));
        } else {
            out.push_back(static_cast<char>(ch));
        }
    }
}

inline bool contains_any(std::string_view hay, std::initializer_list<const char*> needles) {
    for (const char* needle : needles) {
        if (hay.find(needle) != std::string_view::npos) {
            return true;
        }
    }
    return false;
}

}  // namespace

extern "C" {

// Masks:
//   bit 0 (1):  TODO / FIXME / PLACEHOLDER / TBD
//   bit 1 (2):  NotImplementedError
//   bit 2 (4):  Banded AI slop phrases ("stub implementation", "for brevity", etc.)
//   bit 3 (8):  Tautological test assertions ("assert true", "expect(true).tobe(true)", etc.)
//   bit 4 (16): Unsafe sinks ("dangerouslysetinnerhtml", "eval(", "shell=true")
int32_t slopguard_scan_bytes(
    const uint8_t* data,
    int32_t len,
    int32_t* out_lines,
    int32_t* out_masks,
    int32_t max_out,
    int32_t* out_total_lines
) {
    if (out_total_lines != nullptr) {
        *out_total_lines = 0;
    }
    if (len <= 0 || data == nullptr) {
        return 0;
    }

    int32_t line_num = 0;
    int32_t matched_count = 0;
    int32_t idx = 0;
    std::string lower_buf;

    while (idx < len) {
        ++line_num;
        int32_t nl = idx;
        while (nl < len && data[nl] != '\n') {
            ++nl;
        }
        const int32_t end = (nl > idx && data[nl - 1] == '\r') ? (nl - 1) : nl;
        append_ascii_lower(data, idx, end, lower_buf);
        const std::string_view sv(lower_buf);

        int32_t mask = 0;
        if (contains_any(sv, {"todo", "fixme", "placeholder", "coming soon", "lorem ipsum"})) {
            mask |= 1;
        }
        if (contains_any(sv, {"notimplementederror"})) {
            mask |= 2;
        }
        if (contains_any(
                sv,
                {
                    "stub implementation",
                    "for brevity",
                    "dummy return",
                    "mock response",
                    "in production, replace",
                    "simulated only",
                }
            )) {
            mask |= 4;
        }
        if (contains_any(
                sv,
                {
                    "assert true",
                    "expect(true).tobe(true)",
                    "expect(true).toequal(true)",
                    "expect(1).tobe(1)",
                }
            )) {
            mask |= 8;
        }
        if (contains_any(sv, {"dangerouslysetinnerhtml", "eval(", "shell=true"})) {
            mask |= 16;
        }

        if (mask != 0 && out_lines != nullptr && out_masks != nullptr && matched_count < max_out) {
            out_lines[matched_count] = line_num;
            out_masks[matched_count] = mask;
            ++matched_count;
        }
        idx = nl + 1;
    }

    if (out_total_lines != nullptr) {
        *out_total_lines = line_num;
    }
    return matched_count;
}

// Returns Gate Verdict code: 0 = PASS, 1 = WARN, 2 = BLOCK
int32_t slopguard_aggregate_risk(
    const int32_t* severity_weights,
    const int32_t* is_blocker,
    int32_t n,
    int32_t total_lines,
    int32_t* out_blocker_count,
    int32_t* out_risk_score
) {
    if (out_blocker_count != nullptr) {
        *out_blocker_count = 0;
    }
    if (out_risk_score != nullptr) {
        *out_risk_score = 0;
    }
    if (n <= 0 || severity_weights == nullptr || is_blocker == nullptr) {
        return 0;
    }

    int64_t weight_sum = 0;
    int32_t blockers = 0;
    for (int32_t i = 0; i < n; ++i) {
        if (severity_weights[i] > 0) {
            weight_sum += static_cast<int64_t>(severity_weights[i]);
        }
        if (is_blocker[i] != 0) {
            ++blockers;
        }
    }

    const int64_t safe_lines = static_cast<int64_t>(std::max<int32_t>(1, total_lines));
    const int64_t density_bonus = std::min<int64_t>(30, (static_cast<int64_t>(n) * 100LL) / safe_lines);
    const int32_t risk = static_cast<int32_t>(std::min<int64_t>(100, weight_sum + density_bonus));

    if (out_blocker_count != nullptr) {
        *out_blocker_count = blockers;
    }
    if (out_risk_score != nullptr) {
        *out_risk_score = risk;
    }

    if (blockers > 0 || risk >= 60) {
        return 2;
    }
    if (risk >= 25) {
        return 1;
    }
    return 0;
}

}  // extern "C"
