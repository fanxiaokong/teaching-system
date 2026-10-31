-- ============================================================
--  netlab_practice —— 本机练习沙盒的示例数据
--  所有密码哈希都对应明文：test1234
-- ============================================================
USE netlab_practice;

-- ---------- 账号 ----------
INSERT INTO users (username, phone, password_hash, nickname, student_no,
                   is_admin, is_active, quota_mb, created_at, last_login_at) VALUES
('demo_admin',  '13900000001', 'pbkdf2_sha256$40df4ca367385702958fe57a3358127c$b74fea9a846bb6cfcd906521ea37350497eae99fc40cc4234b5b6050f1465719', '演示管理员', '',           1, 1, 999999, '2026-09-01 09:00:00', '2026-10-16 08:30:00'),
('demo_teacher','13900000002', 'pbkdf2_sha256$40df4ca367385702958fe57a3358127c$b74fea9a846bb6cfcd906521ea37350497eae99fc40cc4234b5b6050f1465719', '演示老师',   '',           1, 1, 5120,   '2026-09-02 10:00:00', NULL),
('stu_zhangsan','13900000011', 'pbkdf2_sha256$40df4ca367385702958fe57a3358127c$b74fea9a846bb6cfcd906521ea37350497eae99fc40cc4234b5b6050f1465719', '张三',       '20250001',   0, 1, 200,    '2026-09-10 11:20:00', '2026-10-15 20:11:00'),
('stu_lisi',    '13900000012', 'pbkdf2_sha256$40df4ca367385702958fe57a3358127c$b74fea9a846bb6cfcd906521ea37350497eae99fc40cc4234b5b6050f1465719', '李四',       '20250002',   0, 1, 200,    '2026-09-10 11:25:00', '2026-10-14 19:02:00'),
('stu_wangwu',  '13900000013', 'pbkdf2_sha256$40df4ca367385702958fe57a3358127c$b74fea9a846bb6cfcd906521ea37350497eae99fc40cc4234b5b6050f1465719', '王五',       '20250003',   0, 1, 200,    '2026-09-10 11:30:00', NULL),
('stu_zhaoliu', '13900000014', 'pbkdf2_sha256$40df4ca367385702958fe57a3358127c$b74fea9a846bb6cfcd906521ea37350497eae99fc40cc4234b5b6050f1465719', '赵六',       '20250004',   0, 0, 200,    '2026-09-10 11:35:00', NULL);

-- ---------- 课程 ----------
INSERT INTO courses (title, summary, category, icon, source, content_html, entry_path,
                     sort_order, is_open, created_at, updated_at) VALUES
('网络基础',        '认识交换机、路由器与 IP 地址', '专业基础', '🌐', 'editor', '<p>示例课件</p>', '', 10, 1, '2026-09-01 09:00:00', NULL),
('交换路由配置',    'VLAN、Trunk、静态路由实操',   '专业核心', '🔀', 'editor', '<p>示例课件</p>', '', 20, 1, '2026-09-01 09:10:00', NULL),
('职教高考 · 汉字录入', '指法与速度训练',          '职教高考', '⌨️', 'html',   '', '/courses/zjdk/typing/index.html', 30, 1, '2026-09-30 08:00:00', NULL),
('（草稿）综合布线', '还没写完的课',               '专业基础', '🧰', 'editor', '', '', 99, 0, '2026-09-20 15:00:00', NULL);

-- ---------- 视频 ----------
INSERT INTO videos (course_id, title, description, stored_name, original_name, size,
                    sort_order, created_at, duration, subtitle, subtitle_name) VALUES
(1, '第一讲 网络概述',   '绪论', 'v_demo_001.mp4', '第一讲.mp4', 104857600, 10, '2026-09-01 09:30:00', '18:20', '', ''),
(1, '第二讲 OSI 七层',   '分层模型', 'v_demo_002.mp4', '第二讲.mp4', 209715200, 20, '2026-09-01 09:35:00', '25:04', '', ''),
(2, 'VLAN 划分实操',     '真机演示', 'v_demo_003.mp4', 'VLAN.mp4',  314572800, 10, '2026-09-02 10:30:00', '31:12', '', ''),
(2, 'Trunk 与 Access',   '端口类型', 'v_demo_004.mp4', 'Trunk.mp4', 157286400, 20, '2026-09-02 10:40:00', '22:47', '', '');

-- ---------- 作业 ----------
INSERT INTO assignments (course_id, title, description, deadline, is_open, sort_order, created_at) VALUES
(1, '实验一：制作双绞线', '按 T568B 标准', '2026-10-31 23:59', 1, 10, '2026-09-05 08:00:00'),
(2, '实验二：VLAN 配置',  '交配置截图',    '2026-11-15 23:59', 1, 10, '2026-09-06 08:00:00'),
(2, '（已关）实验三',     '暂不收',        '',                   0, 20, '2026-09-07 08:00:00');

-- ---------- 资料 / 云盘文件 ----------
INSERT INTO files (kind, title, description, stored_name, original_name, size, category,
                   course_id, challenge_id, owner_id, created_at, assignment_id) VALUES
('resource',   '实验指导书.pdf',   '', 'f_demo_001.pdf', '实验指导书.pdf', 2097152, '专业基础', 1, NULL, 2, '2026-09-03 09:00:00', NULL),
('resource',   'VLAN 拓扑图.png',  '', 'f_demo_002.png', '拓扑图.png',     524288, '专业核心', 2, NULL, 2, '2026-09-03 09:10:00', NULL),
('drive',      '张三的作业.zip',   '', 'f_demo_003.zip', '作业.zip',      1048576, '',        NULL, NULL, 3, '2026-10-10 21:00:00', NULL),
('submission', '实验一提交.zip',   '', 'f_demo_004.zip', '实验一.zip',     786432, '',       NULL, NULL, 3, '2026-10-12 20:30:00', 1);

-- ---------- 学习记录 ----------
INSERT INTO study_days (user_id, day, seconds) VALUES
(3, '2026-10-14', 3600),
(3, '2026-10-15', 5400),
(4, '2026-10-14', 1800),
(4, '2026-10-15', 2700);

INSERT INTO course_progress (user_id, course_id, percent, status, updated_at) VALUES
(3, 1, 100, 'done',    '2026-10-15 21:00:00'),
(3, 2, 40,  'learning','2026-10-15 21:05:00'),
(4, 1, 65,  'learning','2026-10-14 19:30:00');

-- ---------- 站点配置 ----------
INSERT INTO settings (k, v) VALUES
('site_title',         '【演示】教学管理系统'),
('site_subtitle',      '这是一份练习用的站点配置'),
('join_open',          '1'),
('register_open',      '1'),
('registration_open',  '1'),
('group_number',       '1053898113'),
('contact_info',       '管理员:QQ2559709613');

-- ---------- 导航链接 ----------
INSERT INTO nav_links (group_name, title, url, icon, description, sort_order, created_at) VALUES
('常用链接', '学校官网',   'https://www.xxcit.edu.cn', '🏫', '', 10, '2026-09-01 09:00:00'),
('常用链接', '教务系统',   'https://jwc.xxcit.cn',      '📚', '', 20, '2026-09-01 09:00:00'),
('学习资源', '华为 eNSP',  'https://e.huawei.com',      '🧪', '', 10, '2026-09-01 09:00:00');

-- ---------- 激活码 ----------
INSERT INTO activation_codes (code, note, created_by, created_at, used_by, used_at) VALUES
('DEMO-CODE-0001', '给张三的',   1, '2026-09-10 09:00:00', 3,    '2026-09-10 11:30:00'),
('DEMO-CODE-0002', '还没人用',   1, '2026-09-10 09:00:00', NULL, NULL),
('DEMO-CODE-0003', '还没人用',   1, '2026-09-10 09:00:00', NULL, NULL);

-- ---------- 社区 ----------
INSERT INTO posts (user_id, title, content, views, is_top, created_at) VALUES
(3, '交换机选型求建议', '预算有限，锐捷还是华为？', 12, 0, '2026-10-08 20:00:00'),
(2, '【置顶】实验室开放时间', '周一至周五 14:00-18:00', 88, 1, '2026-09-01 09:00:00');

INSERT INTO replies (post_id, user_id, content, created_at) VALUES
(1, 4, '我们班用的锐捷，够用', '2026-10-08 21:10:00'),
(1, 2, '看课程需要，两种都行', '2026-10-09 08:20:00');

-- ---------- 招新 / 报名 / 报告 ----------
INSERT INTO join_requests (name, college, contact, join_group, note, created_at, ip) VALUES
('陈同学', '信息工程学院', 'QQ123456789', 1, '想学网络', '2026-10-05 10:00:00', '10.0.0.5'),
('林同学', '人工智能学院', '13900000099', 0, '',        '2026-10-06 11:00:00', '10.0.0.9');

INSERT INTO registrations (name, college, class_name, contact, note, created_at, ip) VALUES
('周同学', '信息工程学院', '网络2301', 'QQ987654321', '', '2026-10-07 09:00:00', '10.0.0.7');

INSERT INTO reports (user_id, name, college, major_class, joined_qq, status, review_note,
                     reviewed_by, created_at, reviewed_at) VALUES
(3, '张三', '信息工程学院', '网络2301', 1, 'pending', '', NULL, '2026-09-22 07:02:58', NULL);

-- ---------- 反馈 ----------
INSERT INTO feedback (user_id, title, category, content, status, created_at, updated_at, replied_at, replied_by) VALUES
(3, '视频加载慢', '体验问题', '晚上看视频要缓冲很久', 'open', '2026-10-12 19:21:30', NULL, NULL, NULL);

INSERT INTO feedback_replies (feedback_id, user_id, is_admin, content, created_at) VALUES
(1, 2, 1, '收到，正在排查带宽', '2026-10-12 20:00:00');

-- ---------- 挑战 ----------
INSERT INTO challenges (title, summary, content_html, difficulty, deadline, is_open, sort_order, created_at) VALUES
('VLAN 排错挑战', '给你一段错配置，找出问题', '<p>题目内容</p>', 2, '2026-12-31 23:59', 1, 10, '2026-09-15 09:00:00'),
('IP 规划挑战',  '给 200 台机器划子网',      '<p>题目内容</p>', 3, '',                1, 20, '2026-09-16 09:00:00');

-- ---------- 题库（示例两题） ----------
INSERT INTO questions (qtype, stem, options, answer, analysis, tag, difficulty, created_at) VALUES
('single', '交换机工作在 OSI 的哪一层？', '["物理层","数据链路层","网络层","传输层"]', 'B', '交换机依据 MAC 地址转发，属数据链路层', '网络基础', 1, '2026-09-01 09:00:00'),
('judge',  'VLAN 可以隔离广播域。',        '["正确","错误"]',                        'A', '每个 VLAN 是一个独立广播域', '交换技术', 1, '2026-09-01 09:00:00');

-- ---------- App 版本 ----------
INSERT INTO app_versions (version_code, version_name, release_notes, file_name, file_size,
                          download_url, is_latest, created_at, platform, sha512) VALUES
(2, 'v1.0.2', '修了些小问题',   'teaching-system-android-v1.0.2.apk', 10485760, '/static/app/teaching-system-android-v1.0.2.apk', 0, '2026-09-20 10:00:00', 'android', 'demo0000'),
(3, 'v1.0.3', '新版本',         'teaching-system-android-v1.0.3.apk', 11534336, '/static/app/teaching-system-android-v1.0.3.apk', 1, '2026-10-05 10:00:00', 'android', 'demo1111');
