// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

// ── Teamspaces ──────────────────────────────────────────────────────

export type TeamRole = "owner" | "reviewer" | "member";

export type TeamVisibility = "public" | "private";

export interface Team {
	id: string;
	name: string;
	handle: string;
	description?: string | null;
	visibility?: TeamVisibility;
	is_personal?: boolean;
	visibility_request_status?: "pending" | "approved" | "rejected" | null;
	visibility_rejection_reason?: string | null;
	role?: TeamRole | null;
	member_count?: number | null;
	created_at?: string;
}

export interface TeamVisibilityRequest {
	team_id: string;
	name: string;
	handle: string;
	description?: string | null;
	requested_by: string | null;
	requested_by_username?: string | null;
	requested_at: string;
}

export interface TeamMember {
	id: string;
	email: string;
	username?: string | null;
	name?: string | null;
	role: TeamRole;
}

export interface TeamUpdateBody {
	name?: string;
	description?: string;
}

export interface TeamMemberUpsertBody {
	email?: string;
	username?: string;
	user_id?: string;
	role?: TeamRole;
}

export type TeamInviteState = "active" | "expired" | "revoked" | "exhausted";

export interface TeamInvite {
	id: string;
	team_id: string;
	name: string;
	url?: string | null;
	invited_by_username?: string | null;
	max_uses?: number | null;
	use_count: number;
	expires_at: string;
	revoked_at?: string | null;
	created_at?: string | null;
	state: TeamInviteState;
}

export interface TeamInviteCreated extends TeamInvite {
	token: string;
	url: string;
}

export interface TeamInvitePreview {
	valid: boolean;
	invite_state?: TeamInviteState | null;
	is_member: boolean;
	team_id?: string | null;
	team_name?: string | null;
	team_handle?: string | null;
	team_description?: string | null;
	invited_by?: string | null;
	request?: {
		id: string;
		status: TeamJoinRequestStatus;
		decision_reason?: string | null;
		created_at?: string | null;
		decided_at?: string | null;
	} | null;
}

export type TeamJoinRequestStatus = "pending" | "approved" | "rejected" | "cancelled";

export interface TeamJoinRequest {
	id: string;
	team_id: string;
	user_id: string;
	invite_id?: string | null;
	email?: string | null;
	username?: string | null;
	name?: string | null;
	status: TeamJoinRequestStatus;
	message?: string | null;
	decided_by?: string | null;
	decided_by_username?: string | null;
	decided_at?: string | null;
	decision_reason?: string | null;
	created_at?: string | null;
}
