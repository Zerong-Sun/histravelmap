import { useState, useRef, useEffect } from "react";
import { Search, X, Clock, TrendingUp } from "lucide-react";

interface SearchBarProps {
  onSearch: (query: string) => void;
}

const POPULAR_SEARCHES = ["马可波罗", "丝绸之路", "长城", "长安", "Odyssey", "Marco Polo"];

export function SearchBar({ onSearch }: SearchBarProps) {
  const [value, setValue] = useState("");
  const [focused, setFocused] = useState(false);
  const [recentSearches, setRecentSearches] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("hismap_recent_searches") || "[]"); } catch { return []; }
  });
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setFocused(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (value.trim()) {
      onSearch(value.trim());
      saveRecent(value.trim());
      setFocused(false);
    }
  };

  const saveRecent = (q: string) => {
    const next = [q, ...recentSearches.filter((s) => s !== q)].slice(0, 5);
    setRecentSearches(next);
    localStorage.setItem("hismap_recent_searches", JSON.stringify(next));
  };

  const handleQuickSearch = (q: string) => {
    setValue(q);
    onSearch(q);
    saveRecent(q);
    setFocused(false);
  };

  const clearValue = () => {
    setValue("");
    onSearch("");
    inputRef.current?.focus();
  };

  const showDropdown = focused && (recentSearches.length > 0 || POPULAR_SEARCHES.length > 0);

  return (
    <div ref={wrapperRef} className="relative w-full max-w-xl">
      <form onSubmit={handleSubmit}>
        <div className={`relative transition-all duration-300 ${focused ? 'scale-[1.02]' : ''}`}>
          <Search className={`absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 transition-colors duration-200 ${focused ? 'text-amber-400' : 'text-gray-400'}`} />
          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onFocus={() => setFocused(true)}
            placeholder="搜索游记、地点、关键词..."
            className="w-full pl-10 pr-9 py-2.5 rounded-xl text-sm transition-all duration-300 outline-none"
            style={{
              background: focused ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.08)',
              border: focused ? '1px solid rgba(201,168,76,0.5)' : '1px solid rgba(255,255,255,0.1)',
              color: 'white',
            }}
          />
          {value && (
            <button
              type="button"
              onClick={clearValue}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white transition-colors"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </form>

      {/* Dropdown */}
      {showDropdown && (
        <div
          className="absolute top-full left-0 right-0 mt-2 rounded-xl overflow-hidden animate-fade-in-down z-50"
          style={{
            background: 'rgba(34, 34, 64, 0.95)',
            backdropFilter: 'blur(16px)',
            border: '1px solid rgba(201,168,76,0.2)',
            boxShadow: '0 12px 40px rgba(0,0,0,0.3)',
          }}
        >
          {recentSearches.length > 0 && (
            <div className="p-3">
              <div className="flex items-center gap-1.5 mb-2">
                <Clock className="h-3 w-3 text-gray-500" />
                <span className="text-[11px] text-gray-500 uppercase tracking-wider">最近搜索</span>
              </div>
              {recentSearches.map((s) => (
                <button
                  key={s}
                  onClick={() => handleQuickSearch(s)}
                  className="w-full text-left px-2.5 py-1.5 text-sm text-gray-300 hover:text-white hover:bg-white/5 rounded-lg transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          <div className="p-3 border-t border-white/5">
            <div className="flex items-center gap-1.5 mb-2">
              <TrendingUp className="h-3 w-3 text-amber-500" />
              <span className="text-[11px] text-amber-500/70 uppercase tracking-wider">热门搜索</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {POPULAR_SEARCHES.map((s) => (
                <button
                  key={s}
                  onClick={() => handleQuickSearch(s)}
                  className="px-2.5 py-1 text-xs text-amber-200/80 rounded-full transition-all hover:text-white hover:bg-amber-500/20"
                  style={{ border: '1px solid rgba(201,168,76,0.2)' }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
