import { IconFolderPlus, type Icon } from "@tabler/icons-react";

export type QuickActionKey = "new-project";

interface QuickAction {
  key: QuickActionKey;
  title: string;
  subtitle: string;
  icon: Icon;
  iconBg: string;
  iconColor: string;
}

const ACTIONS: QuickAction[] = [
  {
    key: "new-project",
    title: "New project",
    subtitle: "Set up a project workspace",
    icon: IconFolderPlus,
    iconBg: "bg-brand-50",
    iconColor: "text-brand-500",
  },
];

const CARD_CLASS =
  "block w-full text-left rounded-lg border border-line-tertiary bg-bg-primary p-4 transition-colors hover:border-line-secondary hover:bg-bg-tertiary";

function ActionBody({ action }: { action: QuickAction }) {
  const Icon = action.icon;
  return (
    <>
      <span
        className={`flex h-10 w-10 items-center justify-center rounded-lg ${action.iconBg}`}
      >
        <Icon size={20} className={action.iconColor} stroke={1.8} />
      </span>
      <div className="mt-8 text-h3 text-ink-primary">{action.title}</div>
      <div className="mt-0.5 text-small text-ink-tertiary">
        {action.subtitle}
      </div>
    </>
  );
}

export function QuickActionGrid({
  onAction,
}: {
  onAction: (key: QuickActionKey) => void;
}) {
  return (
    <section>
      <h2 className="text-h2 text-ink-primary">Quick actions</h2>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {ACTIONS.map((a) => (
          <button
            key={a.key}
            type="button"
            onClick={() => onAction(a.key)}
            className={CARD_CLASS}
          >
            <ActionBody action={a} />
          </button>
        ))}
      </div>
    </section>
  );
}
