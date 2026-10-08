import { Link } from "react-router-dom";

import { toggleTheme, useTheme } from "../lib/theme";
import Icon from "./Icon";

export function ThemeButton() {
  const theme = useTheme();
  const dark = theme === "dark";
  return (
    <button className="icon-btn" onClick={toggleTheme} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}>
      <Icon name={dark ? "sun" : "moon"} />
    </button>
  );
}

export default function Header({ back, title }: { back?: { to: string; label: string }; title?: string }) {
  return (
    <header className="top">
      <div className="wrap top-in">
        {back ? (
          <>
            <Link className="icon-btn" to={back.to} aria-label={`Back to ${back.label}`}>
              <Icon name="back" />
            </Link>
            <span className="top-title">{title ?? back.label}</span>
          </>
        ) : (
          <span className="logo">ARAL</span>
        )}
        <ThemeButton />
      </div>
    </header>
  );
}
