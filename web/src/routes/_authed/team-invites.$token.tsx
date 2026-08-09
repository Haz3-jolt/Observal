// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { createFileRoute, Link } from "@tanstack/react-router";
import { Building2, CheckCircle2, Clock, Loader2, Lock, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layouts/page-header";
import { ErrorState } from "@/components/shared/error-state";
import { useCancelJoinRequest, useRequestJoin, useTeamInvitePreview } from "@/hooks/use-api";

function TeamInvitePage() {
	const { token } = Route.useParams();
	const preview = useTeamInvitePreview(token);
	const teamId = preview.data?.team_id ?? undefined;
	const requestJoin = useRequestJoin(teamId);
	const cancelRequest = useCancelJoinRequest(teamId);
	const request = preview.data?.request;
	const isMember = preview.data?.is_member === true;

	function requestToJoin() {
		requestJoin.mutate({ invite_token: token }, { onSuccess: () => preview.refetch() });
	}

	function withdrawRequest() {
		if (!request) return;
		cancelRequest.mutate(request.id, { onSuccess: () => preview.refetch() });
	}

	const unavailable = !preview.data?.team_id || (!preview.data.valid && !request);

	return (
		<>
			<PageHeader title="Private teamspace invitation" breadcrumbs={[{ label: "Registry", href: "/" }]} />
			<main className="flex min-h-[60vh] items-center justify-center p-6">
				{preview.isLoading ? (
					<Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
				) : preview.isError ? (
					<ErrorState message={preview.error?.message} onRetry={() => preview.refetch()} />
				) : unavailable ? (
					<div className="max-w-md rounded-lg border bg-card p-8 text-center">
						<Lock className="mx-auto h-10 w-10 text-muted-foreground" />
						<h1 className="mt-4 text-xl font-semibold">Invite unavailable</h1>
						<p className="mt-2 text-sm text-muted-foreground">This link is invalid, expired, exhausted, or revoked.</p>
						<Button asChild className="mt-6"><Link to="/">Back to registry</Link></Button>
					</div>
				) : (
					<div className="w-full max-w-lg rounded-lg border bg-card p-8 text-center shadow-sm">
						{isMember ? (
							<CheckCircle2 className="mx-auto h-10 w-10 text-success" />
						) : request?.status === "pending" ? (
							<Clock className="mx-auto h-10 w-10 text-primary-accent" />
						) : request?.status === "rejected" || request?.status === "cancelled" ? (
							<XCircle className="mx-auto h-10 w-10 text-muted-foreground" />
						) : (
							<Building2 className="mx-auto h-10 w-10 text-primary-accent" />
						)}
						<h1 className="mt-4 text-2xl font-semibold">{preview.data?.team_name}</h1>
						<p className="mt-1 font-mono text-xs text-muted-foreground">{preview.data?.team_handle}</p>
						{preview.data?.team_description && <p className="mt-4 text-sm text-muted-foreground">{preview.data.team_description}</p>}
						{preview.data?.invited_by && <p className="mt-3 text-xs text-muted-foreground">Invited by {preview.data.invited_by}</p>}

						{isMember ? (
							<div className="mt-6 space-y-3">
								<p className="text-sm text-success">
									{request?.status === "approved" ? "Join request approved. You are now a member." : "You are already a member."}
								</p>
								<Button asChild><Link to="/teamspaces/$handle" params={{ handle: preview.data?.team_handle ?? "" }}>Open teamspace</Link></Button>
							</div>
						) : request?.status === "pending" ? (
							<div className="mt-6 space-y-3">
								<p className="text-sm text-primary-accent">Join requested. A teamspace owner must approve you.</p>
								<Button variant="outline" disabled={cancelRequest.isPending} onClick={withdrawRequest}>
									{cancelRequest.isPending && <Loader2 className="animate-spin" />} Withdraw request
								</Button>
							</div>
						) : request?.status === "approved" ? (
							<div className="mt-6 space-y-3">
								<p className="text-sm text-muted-foreground">You left this teamspace.</p>
								{preview.data?.valid && <Button disabled={requestJoin.isPending} onClick={requestToJoin}>Request to join again</Button>}
							</div>
						) : request?.status === "rejected" ? (
							<div className="mt-6 space-y-3">
								<p className="text-sm text-destructive">Join request rejected.</p>
								{request.decision_reason && <p className="text-xs text-muted-foreground">{request.decision_reason}</p>}
								{preview.data?.valid && <Button disabled={requestJoin.isPending} onClick={requestToJoin}>Request to join again</Button>}
							</div>
						) : request?.status === "cancelled" ? (
							<div className="mt-6 space-y-3">
								<p className="text-sm text-muted-foreground">You withdrew this join request.</p>
								{preview.data?.valid && <Button disabled={requestJoin.isPending} onClick={requestToJoin}>Request to join again</Button>}
							</div>
						) : (
							<Button className="mt-6" disabled={requestJoin.isPending} onClick={requestToJoin}>
								{requestJoin.isPending && <Loader2 className="animate-spin" />} Request to join
							</Button>
						)}
					</div>
				)}
			</main>
		</>
	);
}

export const Route = createFileRoute("/_authed/team-invites/$token")({
	component: TeamInvitePage,
});
