import "./globals.css";

export const metadata = {
  title: "aisecurity web console",
  description: "Employee request pages and admin audit/compensation console.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
