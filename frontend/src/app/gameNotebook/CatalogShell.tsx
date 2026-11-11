import { NavLink } from 'react-router-dom';
import type { ReactNode } from 'react';
import './notebookCatalog.css';

export function CatalogShell({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="nb-catalog" aria-label={title}>
      <nav className="nb-tabs" aria-label="我的对局导航">
        <NavLink end to="/games">
          棋谱
        </NavLink>
        <NavLink to="/games/positions">局面收藏</NavLink>
      </nav>
      <header className="nb-page-head">
        <h1>{title}</h1>
        {actions && <div className="nb-actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}
