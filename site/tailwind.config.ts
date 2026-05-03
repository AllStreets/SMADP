import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        ink: {
          950: 'oklch(0.10 0.005 270)',
          900: 'oklch(0.14 0.005 270)',
          850: 'oklch(0.17 0.006 270)',
          800: 'oklch(0.20 0.008 270)',
          750: 'oklch(0.25 0.010 270)',
          700: 'oklch(0.30 0.012 270)',
          600: 'oklch(0.42 0.014 270)',
          500: 'oklch(0.55 0.014 270)',
          400: 'oklch(0.68 0.012 270)',
          300: 'oklch(0.78 0.010 270)',
          200: 'oklch(0.88 0.008 270)',
          100: 'oklch(0.95 0.005 270)',
        },
        brand: {
          50: '#F5F3FF',
          100: '#EDE9FE',
          200: '#DDD6FE',
          300: '#C4B5FD',
          400: '#A78BFA',
          500: '#8B5CF6',
          600: '#7C3AED',
          700: '#6D28D9',
          800: '#5B21B6',
          900: '#4C1D95',
          950: '#2E1065',
        },
        cyber: {
          400: '#22D3EE',
          500: '#06B6D4',
          600: '#0891B2',
        },
        sev: {
          none: '#22C55E',
          low: '#84CC16',
          medium: '#F59E0B',
          high: '#EF4444',
          critical: '#7F1D1D',
        },
        evlevel: {
          'unverified-profile': '#71717A',
          'docs-only': '#A78BFA',
          'profile-verified': '#7C3AED',
          'sandbox-validated': '#22C55E',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
        display: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(124,58,237,0.4), 0 8px 32px -8px rgba(124,58,237,0.55)',
        'glow-sm': '0 0 0 1px rgba(124,58,237,0.30), 0 4px 16px -4px rgba(124,58,237,0.40)',
        'glow-cyber': '0 0 0 1px rgba(6,182,212,0.35), 0 8px 32px -8px rgba(6,182,212,0.45)',
      },
      backgroundImage: {
        'grid-fade':
          'radial-gradient(circle at center, rgba(124,58,237,0.10), transparent 70%)',
      },
      animation: {
        'pulse-slow': 'pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        marquee: 'marquee 40s linear infinite',
        'fade-in': 'fadeIn 0.4s ease-out',
      },
      keyframes: {
        marquee: {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
};

export default config;
