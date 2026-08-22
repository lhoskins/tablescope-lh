import type { ChartOptionDefinition } from "./chart-option-definition";

export const Y_AXIS_SCALE_OPTION: ChartOptionDefinition = {
  key: "yAxisScale",
  label: "Axis units",
  type: "select",
  group: "advanced",
  defaultValue: "none",
  options: [
    { label: "Actual values", value: "none" },
    { label: "Thousands", value: "thousands" },
    { label: "Millions", value: "millions" },
    { label: "Billions", value: "billions" },
  ],
  description: "Like Excel display units: values remain unchanged while axis ticks are divided by the selected unit.",
};
