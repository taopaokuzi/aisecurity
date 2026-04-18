import "./globals.css";

export const metadata = {
  title: "aisecurity employee request ui",
  description: "Employee-facing permission request, status, and detail pages.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
