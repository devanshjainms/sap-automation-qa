// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useNavigate } from "react-router-dom";
import {
  Button,
  Text,
  Tooltip,
  mergeClasses,
} from "@fluentui/react-components";
import {
  Add24Regular,
  WeatherMoon24Regular,
  WeatherSunny24Regular,
} from "@fluentui/react-icons";
import { useTheme } from "../../hooks/useTheme";
import { useStyles } from "../../styles/header.styles";

export function Header() {
  const navigate = useNavigate();
  const classes = useStyles();
  const { isDark, toggle } = useTheme();

  return (
    <header className={classes.header}>
      <div className={classes.brand}>
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <rect width="20" height="20" rx="4" fill="#fff" fillOpacity={0.2} />
          <text
            x="50%"
            y="55%"
            dominantBaseline="middle"
            textAnchor="middle"
            fill="#fff"
            fontSize="10"
            fontWeight="700"
          >
            S
          </text>
        </svg>
        <Text className={classes.title}>SAP Testing Automation</Text>
      </div>

      <div className={classes.actions}>
        <Tooltip content="New chat" relationship="label">
          <Button
            appearance="outline"
            size="small"
            icon={<Add24Regular />}
            className={mergeClasses(classes.headerBtn)}
            onClick={() => navigate("/")}
          >
            New chat
          </Button>
        </Tooltip>
        <Tooltip
          content={isDark ? "Switch to light mode" : "Switch to dark mode"}
          relationship="label"
        >
          <Button
            appearance="subtle"
            size="small"
            icon={isDark ? <WeatherSunny24Regular /> : <WeatherMoon24Regular />}
            className={classes.themeBtn}
            onClick={toggle}
          />
        </Tooltip>
      </div>
    </header>
  );
}
