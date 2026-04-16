import "./globals.css";

export const metadata = {
  title: "aisecurity runtime",
  description: "Minimal Next.js runtime entry for the aisecurity project.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
