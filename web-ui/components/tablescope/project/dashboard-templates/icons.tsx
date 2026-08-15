import type { ComponentType } from "react";
import {
  IconActivity,
  IconAlertTriangle,
  IconBuildingBank,
  IconBuildingFactory2,
  IconChartBar,
  IconGauge,
  IconHeadset,
  IconInbox,
  IconRosetteDiscountCheck,
  IconShieldCheck,
  IconTrendingUp,
  IconUsers,
  type IconProps,
} from "@tabler/icons-react";
import type { DashboardTemplateIcon } from "./types";

const ICONS: Record<DashboardTemplateIcon, ComponentType<IconProps>> = {
  activity: IconActivity,
  alert: IconAlertTriangle,
  availability: IconShieldCheck,
  finance: IconBuildingBank,
  gauge: IconGauge,
  headset: IconHeadset,
  hr: IconUsers,
  manufacturing: IconBuildingFactory2,
  quality: IconRosetteDiscountCheck,
  request: IconInbox,
  sales: IconChartBar,
  trend: IconTrendingUp,
};

export function DashboardTemplateIconView({
  name,
  size = 20,
}: {
  name: DashboardTemplateIcon;
  size?: number;
}) {
  const Icon = ICONS[name] ?? IconActivity;
  return <Icon size={size} aria-hidden="true" />;
}
