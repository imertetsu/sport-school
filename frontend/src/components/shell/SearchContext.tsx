import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

interface SearchState {
  query: string;
  setQuery: (q: string) => void;
}

const SearchContext = createContext<SearchState | null>(null);

export function SearchProvider({ children }: { children: ReactNode }) {
  const [query, setQuery] = useState('');
  const value = useMemo<SearchState>(() => ({ query, setQuery }), [query]);
  return <SearchContext.Provider value={value}>{children}</SearchContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSearch(): SearchState {
  const ctx = useContext(SearchContext);
  if (!ctx) throw new Error('useSearch debe usarse dentro de <SearchProvider>');
  return ctx;
}
