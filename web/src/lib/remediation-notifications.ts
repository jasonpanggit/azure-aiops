/** Safe latest stored execution outcome, never an execution command or delivery receipt. */
export interface RemediationNotification {
  notification_id: string;
  execution_id: string;
  plan_id: string;
  revision: number;
  kind: "attention" | "complete" | "cancelled";
  title: string;
  execution_status: "queued" | "running" | "retrying" | "failed" | "cancelled" | "succeeded";
  reconciliation_status: string;
  recorded_at: string | null;
  target_id: string;
  authority: "none";
}

/** Scoped server-paged latest outcomes; counts exclude inaccessible executions. */
export interface RemediationNotificationInbox {
  notifications: RemediationNotification[];
  authorized_execution_count: number;
  latest_outcome_count: number;
  read_only: true;
  boundary: string;
}
