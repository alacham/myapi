CREATE TABLE nodes (
  id              bigserial NOT NULL UNIQUE,
  name            varchar(255) UNIQUE, 
  internal_id     bigint DEFAULT NULL, 
--state           varchar(255) NOT NULL, 
  lastchange      timestamp DEFAULT now(),
  platform        varchar(255) DEFAULT 'nebula',
  creationtemplate  text DEFAULT NULL,
  PRIMARY KEY (id));

ALTER TABLE nodes
  ADD CONSTRAINT uq_nodes_iid_platform UNIQUE(internal_id, platform);

CREATE TABLE networks (
  id    	bigserial UNIQUE NOT NULL, 
  nebulaid 	bigint UNIQUE,
  size  	bigint,
  vid   	bigint UNIQUE,
  type  	varchar(255), 
  reservedsince timestamp DEFAULT now(),
  PRIMARY KEY (id));


CREATE TABLE interfaces (
  id            bigserial NOT NULL, 
  node_id 	bigint NOT NULL REFERENCES nodes(id) ON DELETE CASCADE, 
  mac_addr      macaddr, 
  ip_addr       inet, 
  net_id        bigint REFERENCES networks(id),
  shaping       varchar(255) DEFAULT 'none|none|none|none', 
  PRIMARY KEY (id));
  

CREATE TABLE tagwords (
    id      bigserial UNIQUE NOT NULL, 
    tag     varchar(255) NOT NULL UNIQUE,
--    parent  bigint REFERENCES tagwords(id) DEFAULT NULL,
    PRIMARY KEY (id));
  
--CREATE TABLE numbered_names (
--    id    bigserial NOT NULL, 
--    tag   varchar(255) NOT NULL UNIQUE,
--    seq   bigint NOT NULL,
--  PRIMARY KEY (id));

CREATE TABLE node_taggings (
  node_id   bigint not null REFERENCES nodes(id) ON DELETE CASCADE,
  tag_id  bigint not null REFERENCES tagwords(id),
  PRIMARY KEY (node_id, tag_id)
);

CREATE TABLE net_taggings (
  net_id   bigint not null REFERENCES networks(id) ON DELETE CASCADE,
  tag_id  bigint not null REFERENCES tagwords(id),
  PRIMARY KEY (net_id, tag_id)
);

CREATE TABLE users (
  id		bigserial UNIQUE NOT NULL,
  name		varchar(255) UNIQUE NOT NULL,
  password	varchar(255) NOT NULL,
  salt		varchar(255) NOT NULL,
  isadmin	bool DEFAULT FALSE,
  nebulauser	varchar(255) DEFAULT NULL,
  PRIMARY KEY (id));

CREATE TABLE templates (
  id           bigserial UNIQUE NOT NULL, 
  name         varchar(255) UNIQUE NOT NULL,
  template     text   NOT NULL,
  defaultvalues text,
  defaultuse   bool,
  userid       bigint REFERENCES users(id),
  platform     varchar(255) DEFAULT 'nebula',
  PRIMARY KEY (id));

--CREATE TABLE virt_links (
--  id    	bigserial UNIQUE NOT NULL, 
--  intf1		bigint REFERENCES interfaces(id),
--  intf2		bigint REFERENCES interfaces(id),
--  bridgenode	bigint REFERENCES nodes(id),
--  PRIMARY KEY (id));

--CREATE TABLE vlink_taggings (
--  link_id   bigint not null REFERENCES virt_links(id) ON DELETE CASCADE,
--  tag_id  bigint not null REFERENCES tagwords(id),
--  PRIMARY KEY (link_id, tag_id)
--);

-- http://www.postgresql.org/docs/8.4/static/sql-update.html RETURNING
