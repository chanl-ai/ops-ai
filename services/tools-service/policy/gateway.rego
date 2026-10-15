# The tool gateway's decision for one call. The gateway sends the tool, its access class from the gateway's own
# registry, the sha256 of the canonical input, the run context and the approval token; it never sends the key.
# The review key is written to data.ops.secrets by the gateway at start, so a caller cannot supply its own.
package ops.gateway

import rego.v1

writes := {"write"}

is_write if input.access in writes

registered if input.run_context.sub in data.ops.identities

# A missing token arrives as JSON null, which Rego treats as defined, so presence is a string check.
has_token if {
	is_string(input.token)
	input.token != ""
}

signed if {
	has_token
	io.jwt.verify_hs256(input.token, data.ops.secrets.review_key)
}

claims := payload if {
	signed
	[_, payload, _] := io.jwt.decode(input.token)
}

approvers := {a | some a in claims.approvers}

reasons contains "tool is not registered with the gateway" if input.access == "unknown"

reasons contains "caller identity is not registered" if not registered

reasons contains "write needs an approval token" if {
	is_write
	not has_token
}

reasons contains "approval token is not signed by the review service" if {
	is_write
	has_token
	not signed
}

reasons contains "approval token was issued for a different input" if {
	is_write
	claims.inputHash != input.input_hash
}

reasons contains "approval token is for another tool" if {
	is_write
	claims.tool != input.tool
}

reasons contains "approval token belongs to another thread" if {
	is_write
	claims.thread != input.run_context.thread
}

reasons contains "approval token is for another step" if {
	is_write
	claims.step != input.run_context.step
}

# The gateway's clock, sent with every call: OPA's own clock (a container's) can lag the host, and a lagging clock
# would accept a token past its expiry. A caller that sends none falls back to OPA's clock.
now_ns := input.now_ns if {
	is_number(input.now_ns)
} else := time.now_ns()

reasons contains "approval token has expired" if {
	is_write
	claims.exp * 1000000000 <= now_ns
}

# The operation's write approval policy, from the gateway's registry: a token naming fewer distinct people is refused.
reasons contains sprintf("this write needs %d approvers; the token has %d", [input.approvers_required, count(approvers)]) if {
	is_write
	claims
	is_number(input.approvers_required)
	count(approvers) < input.approvers_required
}

decision := {"allow": count(reasons) == 0, "reasons": sort([r | some r in reasons])}
