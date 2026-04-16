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
import { getVersion } from "../../lib/api";
import { strings } from "../../lib/strings";
import { getDevUiUrl } from "../../lib/constants";

export function Header() {
  const navigate = useNavigate();
  const classes = useStyles();
  const { isDark, toggle } = useTheme();
  const [updateAvailable, setUpdateAvailable] = useState(false);

  useEffect(() => {
    getVersion()
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
        <Text className={classes.title}>{strings.app.name}</Text>
        {updateAvailable && (
          <Tooltip
            content={strings.version.updateAvailable}
            relationship="label"
          >
            <div className={classes.updateIcon}>
              <ArrowUpload20Regular />
            </div>
          </Tooltip>
        )}
      </div>

      <div className={classes.actions}>
        <Tooltip content={strings.nav.newChat} relationship="label">
          <Button
            appearance="subtle"
            size="small"
            icon={<Add24Regular />}
            className={classes.themeBtn}
            onClick={() => navigate("/")}
          />
        </Tooltip>
        <Tooltip content={strings.nav.serviceStatus} relationship="label">
          <Button
            appearance="subtle"
            size="small"
            icon={<HeartPulse20Regular />}
            className={classes.themeBtn}
            onClick={() => navigate("/status")}
          />
        </Tooltip>
        <Tooltip content={strings.nav.agentDevUi} relationship="label">
          <Button
            appearance="subtle"
            size="small"
            icon={<Wrench20Regular />}
            className={classes.themeBtn}
            onClick={() =>
              window.open(getDevUiUrl(), "_blank", "noopener,noreferrer")
            }
          />
        </Tooltip>
        <Tooltip
          content={
            isDark ? strings.theme.switchToLight : strings.theme.switchToDark
          }
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
