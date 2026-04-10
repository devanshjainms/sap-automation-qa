// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Text, Tooltip } from "@fluentui/react-components";
import {
  Add24Regular,
  WeatherMoon24Regular,
  WeatherSunny24Regular,
  HeartPulse20Regular,
  Wrench20Regular,
  ArrowUpload20Regular,
} from "@fluentui/react-icons";
import { useTheme } from "../../hooks/useTheme";
import { useStyles } from "../../styles/header.styles";

const DEVUI_URL = `${window.location.protocol}//${window.location.hostname}:8080`;

export function Header() {
  const navigate = useNavigate();
  const classes = useStyles();
  const { isDark, toggle } = useTheme();
  const [updateAvailable, setUpdateAvailable] = useState(false);

  useEffect(() => {
    fetch("/api/v1/version")
      .then((r) => r.json())
      .then((d) => setUpdateAvailable(d.update_available === true))
      .catch(() => {});
  }, []);

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
        {updateAvailable && (
          <Tooltip
            content="Update available — fetch latest and restart containers"
            relationship="label"
          >
            <div className={classes.updateIcon}>
              <ArrowUpload20Regular />
            </div>
          </Tooltip>
        )}
      </div>

      <div className={classes.actions}>
        <Tooltip content="New chat" relationship="label">
          <Button
            appearance="subtle"
            size="small"
            icon={<Add24Regular />}
            className={classes.themeBtn}
            onClick={() => navigate("/")}
          />
        </Tooltip>
        <Tooltip content="Service Status" relationship="label">
          <Button
            appearance="subtle"
            size="small"
            icon={<HeartPulse20Regular />}
            className={classes.themeBtn}
            onClick={() => navigate("/status")}
          />
        </Tooltip>
        <Tooltip content="Agent DevUI" relationship="label">
          <Button
            appearance="subtle"
            size="small"
            icon={<Wrench20Regular />}
            className={classes.themeBtn}
            onClick={() =>
              window.open(DEVUI_URL, "_blank", "noopener,noreferrer")
            }
          />
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
